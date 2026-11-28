"""
Prompt 959 (stage B3, «مغز خودکار») - the install step in the notification, the chat words and the test report.

The phone's notification used to say only "در حال نصبِ مغز - چند دقیقه طول می‌کشد" with a bar that moved back and forth (no percent): nobody could tell
a working install from a frozen one. Now the notification carries the percent of the install (a real bar), which step of four it is in, and the time that
has really passed; the steps the engine cannot report are marked «حدودی» everywhere the percent appears, and the copy-paste test report says where the
install is. A status without the new `install` key (an older caller, a hand-made dict) keeps the old words. Nothing here is measured on a phone.
"""
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import body as B
from brain_hub import selftest as S
from persian_brain import hub_messages_body as HB
from persian_brain import hub_messages_ownbrain as BM
from tests.test_body_prompt959 import make
from tests.test_selftest_prompt959 import FakeBrain, collect


def inst(stage="load", step=3, percent=57, stage_percent=50, elapsed=72, estimated=True, slow=False, steps=4):
    return {"stage": stage, "step": step, "steps": steps, "percent": percent, "stage_percent": stage_percent, "elapsed": elapsed, "estimated": estimated,
            "slow": slow}


def installing(**over):
    return {"phase": "installing", "percent": 100, "bytes": 5, "total": 5, "install": inst(**over)}


OLD_TEXT = "فایل بررسی و مغز آزمایش می‌شود؛ چند دقیقه طول می‌کشد."


class DescribeInstallTests(unittest.TestCase):
    def test_an_estimated_step_shows_the_percent_marked_and_the_step_and_the_time(self):
        self.assertEqual(B.describe_ownbrain(installing()), ("در حال نصبِ مغز", "۵۷٪ (حدودی) · مرحلهٔ ۳ از ۴: بارگذاریِ مغز · ۱ دقیقه و ۱۲ ثانیه", 57))

    def test_the_measured_step_is_not_marked(self):
        title, text, percent = B.describe_ownbrain(installing(stage="verify", step=1, percent=15, stage_percent=50, elapsed=9, estimated=False))
        self.assertEqual((title, text, percent), ("در حال نصبِ مغز", "۱۵٪ · مرحلهٔ ۱ از ۴: بررسیِ فایل · ۹ ثانیه", 15))
        self.assertNotIn("حدودی", text)

    def test_every_step_has_its_own_short_name(self):
        names = {}
        for stage, step in (("verify", 1), ("compatibility", 2), ("load", 3), ("smoke", 4)):
            names[stage] = B.describe_ownbrain(installing(stage=stage, step=step))[1].split(": ")[1].split(" · ")[0]
        self.assertEqual(names, {"verify": "بررسیِ فایل", "compatibility": "سازگاری", "load": "بارگذاریِ مغز", "smoke": "آزمایشِ اول"})

    def test_the_percent_is_the_services_and_is_cut_to_0_100(self):
        for given, shown in ((0, 0), (99, 99), (100, 100), (150, 100), (-5, 0), (57.9, 57)):
            with self.subTest(given=given):
                self.assertEqual(B.describe_ownbrain(installing(percent=given))[2], shown)

    def test_the_text_fits_the_notification(self):
        for seconds in (0, 59, 61, 3599, 3600, 10 ** 6):
            text = B.describe_ownbrain(installing(elapsed=seconds, slow=True))[1]
            self.assertLessEqual(len(text), B.MAX_TEXT, text)

    def test_without_the_account_the_old_words_and_the_moving_bar_stay(self):
        for status in ({"phase": "installing", "percent": 100, "bytes": 5, "total": 5}, {"phase": "installing", "install": None},
                       {"phase": "installing", "install": "x"}, {"phase": "installing", "install": {}}):
            with self.subTest(status=str(status)):
                self.assertEqual(B.describe_ownbrain(status), ("در حال نصبِ مغز", OLD_TEXT, -1))

    def test_the_file_being_registered_has_no_step_yet_so_the_old_words_stay(self):
        zero = {"stage": "", "step": 0, "steps": 4, "percent": 0, "stage_percent": None, "elapsed": 3, "estimated": False, "slow": False}
        self.assertEqual(B.describe_ownbrain({"phase": "installing", "install": zero}), ("در حال نصبِ مغز", OLD_TEXT, -1))

    def test_garbage_in_the_account_never_raises_and_never_invents_a_percent(self):
        garbage = (inst(percent="x"), inst(percent=float("nan")), inst(percent=None), inst(stage=[]), inst(stage={}), inst(stage=None), inst(step="2"),
                   inst(elapsed="x"), inst(elapsed=float("inf")), inst(elapsed=-5), inst(elapsed=True), inst(steps=0), inst(step=True),
                   inst(percent=[1]))
        for one in garbage:
            with self.subTest(one=str(one)[:60]):
                got = B.describe_ownbrain({"phase": "installing", "install": one})
                self.assertEqual(len(got), 3)
                self.assertIsInstance(got[1], str)
                self.assertTrue(got[2] == -1 or 0 <= got[2] <= 100)

    def test_other_phases_are_untouched_by_an_install_key(self):
        down = {"phase": "downloading", "percent": 42, "bytes": 1_100_000_000, "total": 2_600_000_000, "eta": 720}
        self.assertEqual(B.describe_ownbrain(dict(down, install=inst())), B.describe_ownbrain(down))


class BodyHearsTheAccountTests(unittest.TestCase):
    def test_the_door_gets_a_real_bar_for_the_install_and_it_moves_with_the_account(self):
        body, door, clock, _hub, _log = make()
        body.on_ownbrain(installing(stage="verify", step=1, percent=10, stage_percent=33, elapsed=3, estimated=False))
        clock.advance(B.MIN_GAP_SECONDS)
        body.on_ownbrain(installing(stage="load", step=3, percent=45, elapsed=40))
        clock.advance(B.MIN_GAP_SECONDS)
        body.on_ownbrain(installing(stage="smoke", step=4, percent=90, elapsed=100))
        holds = [call[1:] for call in door.calls("door.hold")]
        self.assertEqual([call[0] for call in holds], ["در حال نصبِ مغز"] * 3)
        self.assertEqual([call[2] for call in holds], [10, 45, 90], "a determinate bar, no more -1")
        self.assertTrue(holds[0][1].startswith("۱۰٪ · مرحلهٔ ۱ از ۴"), holds[0][1])
        self.assertTrue(holds[2][1].startswith("۹۰٪ (حدودی) · مرحلهٔ ۴ از ۴"), holds[2][1])

    def test_the_same_account_is_not_sent_twice_but_a_new_second_is(self):
        body, door, clock, _hub, _log = make()
        body.on_ownbrain(installing(elapsed=10))
        clock.advance(B.MIN_GAP_SECONDS)
        body.on_ownbrain(installing(elapsed=10))
        self.assertEqual(len(door.calls("door.hold")), 1, "nothing changed: the door is not called again")
        clock.advance(B.MIN_GAP_SECONDS)
        body.on_ownbrain(installing(elapsed=12))
        self.assertEqual(len(door.calls("door.hold")), 2, "the clock of the install moved: that is what keeps the notification visibly alive")

    def test_the_end_of_the_install_releases_the_service(self):
        body, door, clock, _hub, _log = make()
        body.on_ownbrain(installing())
        clock.advance(B.MIN_GAP_SECONDS)
        body.on_ownbrain({"phase": "ready", "install": {"stage": "", "step": 0, "steps": 4, "percent": 0, "stage_percent": None, "elapsed": 0,
                                                         "estimated": False, "slow": False}})
        self.assertEqual(len(door.calls("door.release")), 1)
        self.assertEqual(body.jobs(), [])

    def test_a_download_then_an_install_changes_the_title_and_the_bar_kind(self):
        body, door, clock, _hub, _log = make()
        body.on_ownbrain({"phase": "downloading", "percent": 100, "bytes": 5, "total": 5})
        clock.advance(B.MIN_GAP_SECONDS)
        body.on_ownbrain(installing(stage="verify", step=1, percent=4, estimated=False))
        titles = [call[1] for call in door.calls("door.hold")]
        self.assertEqual(titles, ["در حال گرفتنِ مغز", "در حال نصبِ مغز"])


class ChatWordsTests(unittest.TestCase):
    def status(self, **over):
        return BM.status({"phase": "installing", "title_fa": "مغز آزمایشی", "install": inst(**over)})

    def test_the_old_sentence_is_kept_and_the_account_follows_it(self):
        text = self.status()
        lines = text.split("\n")
        self.assertIn("دارم مغز را نصب و برای بار اول آزمایش می‌کنم", lines[0])
        self.assertTrue(lines[1].startswith("⏳ نصب: ۵۷٪ (حدودی) — مرحلهٔ ۳ از ۴: بارگذاریِ مغز در موتور · ۱ دقیقه و ۱۲ ثانیه از شروعِ نصب گذشته"), lines[1])
        self.assertEqual(len(lines), 3, lines)
        self.assertIn("برآوردِ من از زمانِ گذشته", lines[2])

    def test_a_status_without_the_account_is_exactly_the_old_one(self):
        old = BM.status({"phase": "installing"})
        self.assertEqual(old.count("\n"), 0)
        self.assertEqual(BM.status({"phase": "installing", "install": None}), old)
        self.assertEqual(BM.status({"phase": "installing", "install": {"steps": 0}}), old)

    def test_the_measured_step_shows_the_share_of_the_file_read_and_no_estimate_note(self):
        text = self.status(stage="verify", step=1, percent=15, stage_percent=50, elapsed=9, estimated=False)
        self.assertIn("⏳ نصب: ۱۵٪ — مرحلهٔ ۱ از ۴: بررسیِ فایل (۵۰٪ از فایل خوانده شد) · ۹ ثانیه از شروعِ نصب گذشته", text)
        self.assertNotIn("حدودی", text)
        self.assertNotIn("برآوردِ من", text)

    def test_a_slow_step_says_it_is_slow_and_not_finished(self):
        self.assertNotIn("طولانی‌تر", self.status(slow=False))
        text = self.status(slow=True, elapsed=250)
        self.assertIn("از معمول طولانی‌تر شده ولی هنوز تمام نشده", text)
        self.assertNotIn(BM.RETRY, text, "four minutes is not yet a reason to give up")

    def test_after_a_very_long_time_it_says_what_can_be_done(self):
        text = self.status(slow=True, elapsed=BM._VERY_LONG_INSTALL)
        self.assertIn("برنامه را ببند و دوباره باز کن (چیزی پاک نمی‌شود)", text)
        self.assertIn(BM.RETRY, text)
        self.assertNotIn("برنامه را ببند", self.status(slow=True, elapsed=BM._VERY_LONG_INSTALL - 1))

    def test_the_threshold_is_the_ten_minutes_the_guide_promises(self):
        """The guide tells the user it happens after ten minutes: the number in the code is that number, not just whatever the constant happens to be."""
        self.assertNotIn("برنامه را ببند", self.status(slow=True, elapsed=599))
        self.assertIn("برنامه را ببند", self.status(slow=True, elapsed=600))
        self.assertEqual(BM._VERY_LONG_INSTALL, 600)

    def test_the_text_never_says_a_hundred_percent_while_installing(self):
        for step, stage in ((1, "verify"), (2, "compatibility"), (3, "load"), (4, "smoke")):
            self.assertNotIn("۱۰۰٪", self.status(stage=stage, step=step, percent=99, stage_percent=99, slow=True, elapsed=10 ** 5))

    def test_the_file_being_registered_is_said_in_one_line(self):
        zero = {"stage": "", "step": 0, "steps": 4, "percent": 0, "stage_percent": None, "elapsed": 3, "estimated": False, "slow": False}
        lines = BM.install_lines(zero)
        self.assertEqual(lines, ["⏳ نصب شروع شد؛ فایل در جای مدل‌ها ثبت می‌شود… · ۳ ثانیه از شروعِ نصب گذشته"])

    def test_no_quoted_word_is_new_and_garbage_cannot_break_the_text(self):
        import re
        for one in (inst(), inst(stage="verify", step=1, estimated=False), inst(slow=True, elapsed=10 ** 5), inst(percent="x"), inst(stage=[]),
                    inst(elapsed=float("nan")), inst(steps="4"), inst(step=None)):
            with self.subTest(one=str(one)[:50]):
                text = BM.status({"phase": "installing", "install": one})
                self.assertIsInstance(text, str)
                quoted = set(re.findall("«([^»]+)»", text))
                self.assertTrue(quoted <= {"آماده", BM.RETRY}, quoted)

    def test_the_time_in_words(self):
        for seconds, words in ((0, "۰ ثانیه"), (59, "۵۹ ثانیه"), (59.9, "۵۹ ثانیه"), (60, "۱ دقیقه"), (125, "۲ دقیقه و ۵ ثانیه"), (3600, "۱ ساعت"),
                               (3725, "۱ ساعت و ۲ دقیقه")):
            with self.subTest(seconds=seconds):
                self.assertEqual(BM.elapsed_text(seconds), words)
                self.assertEqual(B._elapsed(seconds), words, "the notification says it the same way")
        for bad in (None, -1, "x", True, float("nan"), float("inf"), [], {}):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(BM.elapsed_text(bad), "")
                self.assertEqual(B._elapsed(bad), "")


class ReportTests(unittest.TestCase):
    def brain_status(self, **over):
        status = {"phase": "installing", "sub": "", "choice": "light", "percent": 100, "bytes": 5, "total": 5, "code": "", "detail": "", "resumable": False,
                  "consent": True, "install": inst(**over)}
        return status

    def test_while_installing_the_report_says_where_the_install_is(self):
        facts = collect(brain=FakeBrain(self.brain_status()))
        brain = facts["ownbrain"]
        self.assertEqual({k: brain["install_" + k] for k in ("step", "steps", "stage", "percent", "elapsed", "estimated")},
                         {"step": 3, "steps": 4, "stage": "load", "percent": 57, "elapsed": 72, "estimated": True})
        self.assertNotIn("install_slow", brain)
        text = HB.selftest(facts)
        self.assertIn("🧩 مغزِ خودکار: در حال نصب · مرحلهٔ ۳ از ۴ (load) · ۵۷٪ (حدودی) · ۷۲ ثانیه از شروعِ نصب", text)

    def test_a_measured_step_is_not_marked_in_the_report(self):
        text = HB.selftest(collect(brain=FakeBrain(self.brain_status(stage="verify", step=1, percent=15, estimated=False))))
        self.assertIn("مرحلهٔ ۱ از ۴ (verify) · ۱۵٪ · ", text)
        self.assertNotIn("(حدودی)", text)

    def test_outside_the_install_the_fact_set_is_exactly_the_old_one(self):
        for phase in ("idle", "downloading", "paused", "failed", "ready"):
            with self.subTest(phase=phase):
                status = dict(self.brain_status(), phase=phase)
                facts = collect(brain=FakeBrain(status))["ownbrain"]
                self.assertEqual(set(facts), {"phase", "sub", "choice", "percent", "bytes", "total", "code", "detail", "resumable", "consent", "known"})

    def test_an_installing_status_without_a_step_adds_nothing(self):
        for install in (None, {}, "x", {"step": 0, "steps": 4}):
            with self.subTest(install=str(install)):
                status = dict(self.brain_status(), install=install)
                facts = collect(brain=FakeBrain(status))["ownbrain"]
                self.assertFalse([key for key in facts if key.startswith("install_")])

    def test_garbage_values_are_cleaned_and_the_report_still_comes_out(self):
        status = self.brain_status(percent="9" * 500, elapsed=[1], stage="load/../secret/path", step="3", estimated="yes")
        facts = collect(brain=FakeBrain(status))
        for key, value in facts["ownbrain"].items():
            self.assertTrue(value is None or isinstance(value, (bool, int, float, str)), key)
            if isinstance(value, str):
                self.assertLessEqual(len(value), 120, key)
        text = HB.selftest(facts)
        self.assertIsInstance(text, str)
        self.assertIn("🧩 مغزِ خودکار:", text)

    def test_the_selftest_function_alone_cleans_the_new_keys(self):
        self.assertEqual(S._ownbrain(FakeBrain(self.brain_status()))["install_stage"], "load")
        self.assertEqual(S._ownbrain(None), {"known": False})


if __name__ == "__main__":
    unittest.main()
