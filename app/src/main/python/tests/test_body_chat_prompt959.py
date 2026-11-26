"""
Prompt 959 (stage B, the body) - the BODY in the chat: the self-test report, the access checklist, the settings pages, the one-time code of an
SMS and the emergency stop.

The chat is driven only through the real front door (HTTP `POST /api/message`) on the installed app (`OwnBrainApp`: the real hub, the real own
brain with a scripted download), and the phone is a hand-written fake of Android's classes (`FakeBodyJava`). The tests prove the app's
LOGIC - what it asks Android for, what it refuses, what it says, what it never stores - not that Android or HyperOS behave like the fake.
"""
import json
import os
import sqlite3
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from native_bridge import body as native_body
from native_bridge import facade
from persian_brain import hub_body, hub_ownbrain
from persian_brain import hub_messages_body as HB
from persian_brain import hub_messages_ownbrain as BM
from tests.body_support_prompt959 import FakeBodyJava
from tests.ownbrain_support_prompt959 import OwnBrainApp, ThreadedOwnBrainApp

READ_SMS = native_body.READ_SMS
POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"
GOOGLE = "G-482913 is your Google verification code"
BANK = "مبلغ 2500000 ریال از حساب شما برداشت شد. مانده 1250000 ریال"
CODE = "482913"


def ago(seconds):
    """The date column of an SMS (milliseconds) `seconds` ago, on the real clock (the door's own clock is the real one in the app)."""
    return int((time.time() - seconds) * 1000)


def wait_until(test, predicate, seconds=15, what="the condition"):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    test.fail("timed out waiting for %s" % what)


class BodyMixin:
    """The fake Android runtime for the body doors, installed before the app starts and removed afterwards."""

    java_kwargs = {}

    def setUp(self):
        facade.reset_for_tests()
        self.addCleanup(facade.reset_for_tests)
        self.java = FakeBodyJava(granted=(POST_NOTIFICATIONS,), **self.java_kwargs)
        facade.set_jvm(self.java)
        super().setUp()

    def files_holding(self, secret):
        """Relative paths of every file under the app's files folder that holds `secret` as plain bytes."""
        needle, found = secret.encode("utf-8"), []
        for folder, _dirs, names in os.walk(self.files):
            for name in names:
                path = os.path.join(folder, name)
                with open(path, "rb") as handle:
                    if needle in handle.read():
                        found.append(os.path.relpath(path, self.files).replace(os.sep, "/"))
        return found

    def dump_lines(self, secret):
        """The lines of a full SQL dump of the app's database that contain `secret`."""
        return [line for line in self.memory._conn.iterdump() if secret in line]

    def history(self):
        status, _type, raw = self.get("/api/history")
        self.assertEqual(status, 200)
        return json.loads(raw.decode("utf-8"))["messages"]


# ============================================================================ the self-test report
class SelfTestChatTests(BodyMixin, OwnBrainApp):
    def test_the_report_is_made_from_what_the_phone_says(self):
        reply = self.ask(HB.SELFTEST_ASK)
        for part in ("🩺 گزارشِ آزمایشی", "نسخهٔ 0.2.0", "(کدِ ۲)", "arm64-v8a", "اندروید SDK ۳۴", "حافظهٔ رم", "موتورِ مغز (LiteRT-LM)", "سرویسِ پس‌زمینه",
                     "مغزِ خودکار", "اینترنتِ برنامه", "مدل‌های ثبت‌شده"):
            self.assertIn(part, reply)
        self.assertIn(BM.size(8_000_000_000), reply, "the memory the phone reported")
        self.assertIn("برنامه معاف نیست", reply, "the fake phone does not exempt the app from battery optimization")

    def test_the_report_changes_with_the_phone(self):
        self.java.ignoring, self.java.power_save = True, True
        reply = self.ask(HB.SELFTEST_ASK)
        self.assertIn("معاف است ✅", reply)
        self.assertIn("حالتِ صرفه‌جوییِ باتری روشن است", reply)

    def test_the_report_has_no_chat_text_no_key_no_code_no_path(self):
        secret_words = "کلمهٔ-محرمانهٔ-آزمایشی-۱۷۳"
        self.ask("سلام، " + secret_words)
        self.java.sms = [("Google", GOOGLE, ago(30))]
        self.java.granted = {POST_NOTIFICATIONS, READ_SMS}
        reply = self.ask(HB.SELFTEST_ASK)
        for private in (secret_words, CODE, "Google", self.files, "/data/", "sk-", "password"):
            self.assertNotIn(private, reply)
        self.assertIn("مجوز داده شده ✅", reply, "it says THAT the SMS permission is given, and nothing of what an SMS holds")
        self.assertEqual(self.java.queries, [], "the report must not read the inbox")

    def test_the_report_says_the_engine_is_missing_with_its_reason(self):
        self.engine_available = False
        self.start_app()
        reply = self.ask(HB.SELFTEST_ASK)
        self.assertIn("موتورِ مغز (LiteRT-LM): ❌", reply)

    def test_the_report_always_comes_out_even_where_nothing_native_works(self):
        facade.set_jvm(None)                                   # no Android at all (a desktop run / an APK without the native piece)
        reply = self.ask(HB.SELFTEST_ASK)
        self.assertIn("🩺 گزارشِ آزمایشی", reply)
        self.assertIn("برنامه: نامعلوم", reply)
        self.assertIn("حافظهٔ رم", reply)
        self.assertIn("پیامک: نامعلوم", reply)

    def test_without_the_word_copy_the_clipboard_is_not_touched_and_the_way_to_copy_is_said(self):
        reply = self.ask(HB.SELFTEST_ASK)
        self.assertIsNone(self.java.clipboard)
        self.assertIn(HB.SELFTEST_COPY, reply)

    def test_with_the_word_copy_the_report_is_on_the_clipboard(self):
        reply = self.ask(HB.SELFTEST_COPY)
        self.assertTrue(self.java.clipboard.startswith("🩺 گزارشِ آزمایشی"), self.java.clipboard)
        self.assertIn("در کلیپ‌بوردِ گوشی گذاشتم", reply)
        self.assertNotIn(HB.SELFTEST_COPY, reply.split("در کلیپ‌بوردِ گوشی گذاشتم")[-1], "no second hint after a copy that worked")

    def test_a_clipboard_that_fails_is_said_plainly(self):
        facade.set_jvm(None)
        reply = self.ask(HB.SELFTEST_COPY)
        self.assertIn("نتوانستم آن را در کلیپ‌بورد بگذارم", reply)

    def test_the_report_names_the_kinds_of_recent_errors_and_never_their_text(self):
        self.memory.log_error("persian_brain", "ValueError: the user said سیب-زمینی-۹۹۱", "متنِ کاربر ۹۹۱")
        self.memory.log_error("persian_brain", "ValueError: again", "x")
        reply = self.ask(HB.SELFTEST_ASK)
        self.assertIn("persian_brain: ValueError ×۲", reply)
        self.assertNotIn("سیب-زمینی", reply)
        self.assertNotIn("۹۹۱", reply)


# ============================================================================ the access checklist and the settings pages
class AccessChatTests(BodyMixin, OwnBrainApp):
    def test_the_checklist_says_what_the_phone_says(self):
        reply = self.ask(HB.ACCESS_ASK)
        self.assertIn("HyperOS", reply)
        self.assertIn("بدون محدودیت", reply)
        self.assertIn("الان معاف نیست ⚠️", reply)
        self.assertIn(HB.OPEN_BATTERY, reply)
        self.java.ignoring = True
        self.assertIn("الان معاف است ✅", self.ask(HB.ACCESS_ASK))

    def test_the_checklist_never_claims_to_see_the_vendors_own_switches(self):
        reply = self.ask(HB.ACCESS_ASK)
        self.assertIn("تنظیمِ ویژهٔ HyperOS را نمی‌بینم", reply)
        self.assertIn("برنامه هیچ‌کدام را نمی‌تواند خودش عوض کند", reply)

    def test_each_settings_page_is_opened_and_nothing_is_changed(self):
        cases = ((HB.OPEN_BATTERY, "BATTERY_OPT"), (HB.OPEN_APP, "APP_DETAILS"), (HB.OPEN_NOTIFICATIONS, "APP_NOTIF"))
        for sentence, action in cases:
            with self.subTest(sentence):
                self.java.started.clear()
                reply = self.ask(sentence)
                self.assertEqual([intent.action for intent in self.java.started], [action])
                self.assertIn("را باز کردم", reply)
                self.assertIn("هیچ‌چیز را عوض نمی‌کنم", reply)

    def test_a_settings_page_outside_an_android_app_is_said_plainly(self):
        facade.set_jvm(None)
        self.assertIn("فقط داخلِ برنامهٔ اندروید", self.ask(HB.OPEN_BATTERY))

    def test_a_refused_page_is_said_plainly(self):
        self.java.raise_on["startActivity"] = RuntimeError("blocked by the vendor")
        reply = self.ask(HB.OPEN_BATTERY)
        self.assertIn("نتوانستم صفحه را باز کنم", reply)
        self.assertNotIn("blocked by the vendor", reply, "the text of a Java error is not shown")

    def test_the_accessibility_settings_command_stays_the_hubs_own(self):
        self.java.started.clear()
        reply = self.ask("تنظیمات دسترسی‌پذیری را باز کن")
        self.assertNotIn("را باز کردم؛ تنظیم با خودت است", reply)

    def test_a_question_about_the_body_is_not_an_order(self):
        for sentence in ("چرا برنامه خودش بسته می‌شود؟", "تنظیمات گوشی برای کار در پس‌زمینه"):
            with self.subTest(sentence):
                self.assertIn("چک‌لیستِ دسترسی‌ها", self.ask(sentence))


# ============================================================================ the one-time code of an SMS
class SmsChatTests(BodyMixin, OwnBrainApp):
    """The code is shown only in the chat; the stored chat history never keeps it for long, and nothing else keeps it at all."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(hub_body, "SCRUB_DELAYS", (0.05, 0.15))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.finish_timers)

    def finish_timers(self):
        for timer in hub_body.pending_timers():
            timer.join(5)

    def allow(self, *sms):
        self.java.granted = {POST_NOTIFICATIONS, READ_SMS}
        self.java.sms = list(sms)

    def masked(self):
        wait_until(self, lambda: not hub_body.pending_timers(), what="the scrub timers")

    # ------------------------------------------------------------------ the permission, step by step
    def test_without_the_permission_the_reply_explains_and_nothing_is_read(self):
        self.java.sms = [("Google", GOOGLE, ago(30))]
        reply = self.ask(HB.SMS_ASK)
        self.assertEqual(reply, HB.sms_need_permission())
        self.assertNotIn(CODE, reply)
        self.assertEqual(self.java.permission_requests, [], "asking for a code never asks Android for the permission by itself")

    def test_the_permission_dialog_is_shown_only_on_his_order(self):
        reply = self.ask(HB.SMS_PERMISSION)
        self.assertEqual(self.java.permission_requests, [[READ_SMS]])
        self.assertEqual(reply, HB.sms_permission_shown())
        self.assertNotIn(READ_SMS, self.java.granted, "the app never grants itself anything: he taps «اجازه»")

    def test_a_permission_that_is_given_already_is_not_asked_again(self):
        self.allow()
        reply = self.ask(HB.SMS_PERMISSION)
        self.assertEqual(self.java.permission_requests, [])
        self.assertEqual(reply, HB.sms_permission_have())

    def test_a_dialog_that_cannot_be_shown_is_said_plainly(self):
        self.java.dialog_allowed = False
        self.assertEqual(self.ask(HB.SMS_PERMISSION), HB.sms_failed("not_allowed"))

    # ------------------------------------------------------------------ the code
    def test_the_newest_code_is_shown_with_its_sender_and_age_and_never_the_message(self):
        self.allow(("Bank", BANK, ago(40)), ("Google", GOOGLE, ago(120)), ("Mom", "ok", ago(300)))
        reply = self.ask(HB.SMS_ASK)
        self.assertTrue(reply.startswith(HB.CODE_PREFIX + CODE), reply)
        self.assertIn("(فرستنده: Google", reply)
        self.assertIn("دقیقه پیش", reply)
        for text in ("Google verification", "is your", "برداشت", "1250000", "2500000"):
            self.assertNotIn(text, reply)
        self.assertEqual(len(self.java.queries), 1)
        self.masked()

    def test_an_old_code_needs_the_longer_ask(self):
        self.allow(("Google", GOOGLE, ago(40 * 60)))
        self.assertEqual(self.ask(HB.SMS_ASK), HB.sms_empty(15))
        reply = self.ask("کد پیامک یک ساعت اخیر را بخوان")
        self.assertIn(CODE, reply)
        self.masked()

    def test_no_message_with_a_code_is_said_plainly(self):
        self.allow(("Bank", BANK, ago(40)), ("Mom", "ok", ago(60)))
        self.assertEqual(self.ask(HB.SMS_ASK), HB.sms_empty(15))

    def test_too_many_asks_are_slowed_down_and_said(self):
        self.allow(("Google", GOOGLE, ago(30)))
        replies = [self.ask(HB.SMS_ASK) for _ in range(8)]
        self.assertEqual(replies[-1], HB.sms_failed("rate_limited"))
        self.assertLessEqual(len(self.java.queries), 6, "the door allows a few reads in ten minutes, no more")
        self.masked()

    def test_a_question_about_codes_is_never_a_read(self):
        self.allow(("Google", GOOGLE, ago(30)))
        for sentence in ("کد تایید چیه؟", "رمز وای‌فای را بگو", "کدی که برام نوشتی رو بخون"):
            with self.subTest(sentence):
                self.assertNotIn(CODE, self.ask(sentence))
        self.assertEqual(self.java.queries, [])

    # ------------------------------------------------------------------ what is kept
    def test_the_stored_history_no_longer_holds_the_code_a_moment_later(self):
        self.allow(("Google", GOOGLE, ago(30)))
        reply = self.ask(HB.SMS_ASK)
        self.assertIn(CODE, reply)
        self.masked()
        rows = self.history()
        self.assertNotIn(CODE, json.dumps(rows, ensure_ascii=False))
        masked = [row["content"] for row in rows if HB.CODE_PREFIX in row["content"]]
        self.assertEqual(len(masked), 1)
        self.assertTrue(masked[0].startswith(HB.CODE_PREFIX + HB.CODE_MASK + "\n" + HB.SENDER_PREFIX + HB.SENDER_MASK), masked[0])
        self.assertIn("کد را به هیچ‌کس نگو", masked[0], "the rest of the reply stays as it was")
        self.assertIn(HB.SMS_ASK, [row["content"] for row in rows], "and so does what the user said")

    def test_the_database_file_no_longer_holds_the_code_bytes(self):
        self.memory._conn.execute("PRAGMA secure_delete = OFF")      # the worst case: a SQLite that leaves old bytes in the file
        self.allow(("Google", GOOGLE, ago(30)))
        self.ask(HB.SMS_ASK)
        self.masked()
        self.assertEqual(self.dump_lines(CODE), [])
        self.memory._conn.commit()
        self.assertEqual(self.files_holding(CODE), [], "no file of the app may hold the code any more")
        self.assertEqual(self.memory._conn.execute("PRAGMA secure_delete").fetchone()[0], 0, "the connection's own setting is put back")

    def test_the_masking_rewrites_the_row_while_secure_delete_is_on_and_puts_the_setting_back(self):
        """Found by a mutation probe: with SQLite's own setting left OFF the row's old bytes can stay in a free block of the file (it depends on
        where the row sits on its page), so the file test above can pass by luck. This one checks the setting itself, at the moment of the UPDATE."""
        self.memory._conn.execute("PRAGMA secure_delete = OFF")
        with mock.patch.object(hub_body, "SCRUB_DELAYS", ()):
            self.allow(("Google", GOOGLE, ago(30)))
            self.ask(HB.SMS_ASK)
        seen, real = [], self.memory._run

        def spy(sql, *args, **kwargs):
            if sql.lstrip().upper().startswith("UPDATE CONVERSATION_LOG"):
                seen.append(self.memory._conn.execute("PRAGMA secure_delete").fetchone()[0])
            return real(sql, *args, **kwargs)

        with mock.patch.object(self.memory, "_run", spy):
            self.assertEqual(hub_body.scrub_codes(self.memory), 1)
        self.assertEqual(seen, [1], "the row is rewritten while SQLite overwrites what it frees")
        self.assertEqual(self.memory._conn.execute("PRAGMA secure_delete").fetchone()[0], 0, "the connection's own setting is put back")

    def test_a_masking_that_could_not_be_planned_is_said_so_in_the_reply(self):
        with mock.patch.object(hub_body, "_plan_scrub", return_value=False):
            self.allow(("Google", GOOGLE, ago(30)))
            reply = self.ask(HB.SMS_ASK)
        self.assertIn(CODE, reply)
        self.assertIn(HB.sms_privacy(scrubbed=False), reply)
        self.assertNotIn(HB.sms_privacy(scrubbed=True), reply, "no promise that nothing stands behind")

    def test_a_masking_that_was_planned_is_promised(self):
        self.allow(("Google", GOOGLE, ago(30)))
        reply = self.ask(HB.SMS_ASK)
        self.assertIn(HB.sms_privacy(scrubbed=True), reply)
        self.assertNotIn(HB.sms_privacy(scrubbed=False), reply)
        self.masked()

    def test_before_the_mask_only_the_chat_history_holds_the_code(self):
        with mock.patch.object(hub_body, "SCRUB_DELAYS", ()):
            self.allow(("Google", GOOGLE, ago(30)))
            self.ask(HB.SMS_ASK)
            lines = self.dump_lines(CODE)
            self.assertEqual(len(lines), 1, lines)
            self.assertTrue(lines[0].startswith('INSERT INTO "conversation_log"'), lines[0])
            plan = self.memory.get_state(hub_body.SCRUB_KEY, None)
            self.assertIsInstance(plan, dict, "the plan to mask it is on record")
            self.assertEqual(sorted(plan), ["ts"], "and it holds a time only")
            self.assertNotIn(CODE, json.dumps([list(e) if isinstance(e, tuple) else e for e in self.hub.audit.entries()], ensure_ascii=False, default=str))

    def test_when_the_app_is_closed_before_the_timers_the_next_message_masks_the_code(self):
        with mock.patch.object(hub_body, "SCRUB_DELAYS", ()):
            self.allow(("Google", GOOGLE, ago(30)))
            self.ask(HB.SMS_ASK)
            self.assertEqual(len(self.dump_lines(CODE)), 1)
            self.start_app()                                          # the app was closed and opened again
            self.assertIn(CODE, json.dumps(self.history(), ensure_ascii=False), "nothing has masked it yet - the history is what the page shows again")
            self.ask("سلام")
            self.assertEqual(self.dump_lines(CODE), [])
            self.assertNotIn(CODE, json.dumps(self.history(), ensure_ascii=False))
            self.assertIsNone(self.memory.get_state(hub_body.SCRUB_KEY, None), "the plan is done and forgotten")
            self.assertEqual(self.files_holding(CODE), [])

    def test_a_masked_history_is_left_alone_by_a_second_pass(self):
        self.allow(("Google", GOOGLE, ago(30)))
        self.ask(HB.SMS_ASK)
        self.masked()
        before = self.history()
        self.assertEqual(hub_body.scrub_codes(self.memory), 0)
        self.assertEqual(self.history(), before)

    def test_two_codes_in_one_history_are_both_masked(self):
        self.allow(("Google", GOOGLE, ago(30)))
        self.ask(HB.SMS_ASK)
        self.java.sms = [("Bank", "رمز یکبار مصرف شما 5678 است", ago(20))]
        self.java.queries.clear()
        facade.reset_for_tests()
        facade.set_jvm(self.java)                                     # a fresh rate window for the second read
        self.ask(HB.SMS_ASK)
        self.masked()
        flat = json.dumps(self.history(), ensure_ascii=False)
        self.assertNotIn(CODE, flat)
        self.assertNotIn("5678", flat)
        self.assertEqual(flat.count(HB.CODE_PREFIX + HB.CODE_MASK), 2)

    def test_the_code_is_not_kept_in_the_error_log_the_state_or_the_audit(self):
        self.allow(("Google", GOOGLE, ago(30)))
        self.ask(HB.SMS_ASK)
        self.masked()
        self.assertEqual(self.dump_lines(CODE), [])
        entries = list(self.hub.audit.entries())
        self.assertTrue(any("native.sms" in json.dumps(e, ensure_ascii=False, default=str) for e in entries), "the read itself is audited ...")
        self.assertNotIn(CODE, json.dumps(entries, ensure_ascii=False, default=str), "... without the code")
        self.assertEqual(self.files_holding(CODE), [])

    def test_the_code_never_reaches_a_model_or_the_cloud(self):
        self.install_light()
        self.allow(("Google", GOOGLE, ago(30)))
        self.bridge.chats.clear()
        self.ask(HB.SMS_ASK)
        self.masked()
        self.assertEqual(self.bridge.chats, [], "reading a code is a command of the body: no model is asked anything")


# ============================================================================ the emergency stop
from persian_brain import hub_brain  # noqa: E402
from persian_brain import hub_messages_brain as HBr  # noqa: E402
from persian_brain import hub_messages_ownbrain as HO  # noqa: E402
from persian_brain.brain import get_brain  # noqa: E402
from tests.ownbrain_support_prompt959 import FakeBridge  # noqa: E402

FREE = "یه سوال عجیب و غریب درباره فلان"


class CancellingBridge(FakeBridge):
    """A fake engine whose `cancel()` makes the answer in progress come back as the real engine's «ERR cancelled»."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cut = False

    def chat(self, system, history, user, max_tokens):
        self.chats.append({"system": system, "history": history, "user": user, "max_tokens": max_tokens})
        if self.gate is not None:
            self.gate.wait(20)
        if self.cut:
            self.cut = False
            return "ERR\ncancelled\n"
        return "OK\n" + self.answers[0]

    def cancel(self):
        self.cancels += 1
        self.cut = self.gate is not None and not self.gate.is_set()      # only an answer that is really in progress is cut
        if self.gate is not None:
            self.gate.set()


class EmergencyAnswerTests(BodyMixin, OwnBrainApp):
    """«ایست» while the local model is making a long answer: the chat is busy with that answer, and the stop must not wait behind it."""

    def setUp(self):
        super().setUp()
        self.bridge = CancellingBridge(answers=self.answers)
        self.start_app()
        self.install_light()

    def ask_in_thread(self, sentence):
        box = {}

        def run():
            box["reply"] = self.ask(sentence)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, box

    def start_slow_answer(self):
        self.bridge.gate = threading.Event()
        before = len(self.bridge.chats)
        thread, box = self.ask_in_thread(FREE)
        wait_until(self, lambda: len(self.bridge.chats) > before, what="the engine to start the answer")
        self.addCleanup(self.bridge.gate.set)
        return thread, box

    def test_the_stop_word_does_not_wait_behind_a_long_answer(self):
        thread, box = self.start_slow_answer()
        began = time.monotonic()
        reply = self.ask("ایست")
        self.assertLess(time.monotonic() - began, 5, "the stop word waited behind the answer")
        self.assertEqual(self.bridge.cancels, 1, "the engine was asked to drop the answer")
        self.assertIn(HBr.halt_done(), reply)
        self.assertIn("به موتورِ مدلِ روی گوشی هم گفتم", reply)
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box["reply"], HO.llm_failed("cancelled"), "the question that was being answered says that its answer was stopped")

    def test_the_stop_word_halts_the_cloud_brain_and_the_word_continue_resumes_it(self):
        thread, _box = self.start_slow_answer()
        self.ask("ایست")
        thread.join(10)
        svc = hub_brain.service(get_brain(self.memory))
        self.assertTrue(svc.settings.get()["halted"])
        self.assertEqual(self.ask("ادامه"), HBr.resume_done())
        self.assertFalse(svc.settings.get()["halted"])

    def test_other_sentences_still_wait_their_turn_and_cancel_nothing(self):
        thread, box = self.start_slow_answer()
        second, second_box = self.ask_in_thread("سلام")
        second.join(1.0)
        self.assertTrue(second.is_alive(), "a sentence that is not the stop word must wait for the running answer")
        self.assertEqual(self.bridge.cancels, 0)
        self.bridge.gate.set()
        thread.join(10)
        second.join(10)
        self.assertFalse(second.is_alive())
        self.assertIn("reply", second_box)
        self.assertEqual(self.bridge.cancels, 0)

    def test_the_stop_word_inside_a_longer_sentence_is_not_the_stop_word(self):
        thread, _box = self.start_slow_answer()
        second, _second_box = self.ask_in_thread("ایست بازرسی یعنی چی؟")
        second.join(1.0)
        self.assertTrue(second.is_alive())
        self.assertEqual(self.bridge.cancels, 0)
        self.bridge.gate.set()
        thread.join(10)
        second.join(10)

    def test_the_notification_button_stops_the_same_answer(self):
        import platform_boot
        from brain_hub import service
        thread, box = self.start_slow_answer()
        with mock.patch.object(service, "live_hubs", return_value=[self.hub]):
            result = json.loads(platform_boot.emergency_stop())
        self.assertTrue(result["ok"])
        self.assertEqual(result["hubs"], 1)
        self.assertIn("engine", result["stopped"])
        thread.join(10)
        self.assertEqual(box["reply"], HO.llm_failed("cancelled"))

    def test_the_stop_closes_an_open_cloud_question_even_behind_a_long_answer(self):
        thread, _box = self.start_slow_answer()
        self.memory.set_state(hub_brain.PENDING_KEY, {"type": "provider", "ts": time.time(), "data": {}})
        self.ask("ایست")
        self.assertIsNone(self.memory.get_state(hub_brain.PENDING_KEY, None), "the open question is closed, as on the normal path")
        thread.join(10)

    def test_a_stop_when_nothing_is_busy_takes_the_normal_path(self):
        reply = self.ask("ایست")
        self.assertIn(HBr.halt_done(), reply)
        self.assertEqual(self.ask("ادامه"), HBr.resume_done())

    def test_a_stop_never_creates_or_halts_what_was_never_switched_on(self):
        self.assertIsNone(self.memory.get_state("brain_v2.settings.v1", None), "the cloud brain was never switched on")
        self.ask("ایست")
        body = __import__("brain_hub.body", fromlist=["peek_body"]).peek_body(self.hub)
        self.assertIsNotNone(body)
        self.assertEqual(body.status()["jobs"], [])


class EmergencyDownloadTests(BodyMixin, ThreadedOwnBrainApp):
    """The download of the own brain keeps the phone's foreground service; the stop lets it go; the end of the download lets it go too."""

    def service_titles(self):
        return [call[1] for call in self.java.service_calls if call[0] == "hold"]

    def test_the_download_holds_the_service_with_its_progress(self):
        self.start_download()
        wait_until(self, lambda: self.java.service_running, what="the foreground service")
        holds = [call for call in self.java.service_calls if call[0] == "hold"]
        self.assertEqual({call[1] for call in holds}, {"در حال گرفتنِ مغز"})
        self.assertTrue(any(call[3] >= 0 for call in holds), "a percent was passed on")
        self.assertIn("از", holds[-1][2])

    def test_the_stop_word_stops_the_download_and_lets_the_service_go(self):
        self.start_download()
        wait_until(self, lambda: self.java.service_running, what="the foreground service")
        reply = self.ask("ایست")
        self.assertIn(BM.halted_note(), reply)
        self.assertEqual(self.ob.status()["phase"], "paused")
        self.assertFalse(self.java.service_running, "the notification is gone")
        self.assertEqual(self.java.service_calls[-1], ("release",))

    def test_the_stop_word_on_the_normal_path_also_runs_the_bodys_own_stop(self):
        """Found by a mutation probe: the body's stop (engine request, cloud, notification) is wired into the normal path of the chat."""
        self.start_download()
        wait_until(self, lambda: self.java.service_running, what="the foreground service")
        with mock.patch.object(hub_body, "after_emergency", side_effect=lambda brain, mine: (mine[0], mine[1] + "\n\nMARK-FROM-THE-BODY")) as hook:
            reply = self.ask("ایست")
        self.assertIn("MARK-FROM-THE-BODY", reply)
        self.assertEqual(hook.call_count, 1)
        self.assertEqual(hook.call_args[0][1][0], "brain_halt", "it gets the stop's own (sub, reply)")

    def test_continue_after_the_stop_holds_the_service_again(self):
        self.start_download()
        self.ask("ایست")
        self.assertFalse(self.java.service_running)
        self.cdn.gate.clear()
        self.ask("ادامه")
        self.assertTrue(self.cdn.reached.wait(15))
        wait_until(self, lambda: self.java.service_running, what="the service after «ادامه»")

    def test_a_finished_download_lets_the_service_go(self):
        self.start_download()
        wait_until(self, lambda: self.java.service_running, what="the foreground service")
        self.open_gate_and_wait()
        self.assertEqual(self.ob.status()["phase"], "ready")
        wait_until(self, lambda: not self.java.service_running, what="the service to be released")
        self.assertEqual(self.java.service_calls[-1], ("release",))

    def test_a_why_question_during_the_download_is_a_question_not_a_stop(self):
        self.start_download()
        reply = self.ask("چرا دانلود قطع میشه؟")
        self.assertIn("چک‌لیستِ دسترسی‌ها", reply)
        self.assertEqual(self.ob.status()["phase"], "downloading")
        self.assertTrue(self.java.service_running)

    def test_the_report_during_the_download_shows_the_job_and_the_service(self):
        self.start_download()
        wait_until(self, lambda: self.java.service_running, what="the foreground service")
        reply = self.ask(HB.SELFTEST_ASK)
        self.assertIn("ownbrain", reply)
        self.assertIn("در حال دانلود", reply)

    def test_the_notification_button_stops_the_download(self):
        import platform_boot
        from brain_hub import service
        self.start_download()
        wait_until(self, lambda: self.java.service_running, what="the foreground service")
        with mock.patch.object(service, "live_hubs", return_value=[self.hub]):
            result = json.loads(platform_boot.emergency_stop())
        self.assertIn("download", result["stopped"])
        self.assertEqual(self.ob.status()["phase"], "paused")
        wait_until(self, lambda: not self.java.service_running, what="the service to be released")


class EmergencyInstallTests(BodyMixin, ThreadedOwnBrainApp):
    """The step after the download (verify, load, the first test question) cannot be interrupted (stage B, the own brain): the stop must not ask
    the engine to drop that question, must not take the notification away from under it, and must say so - in every way it can arrive. The
    engine is a fake whose first question is held by the test."""

    def setUp(self):
        super().setUp()
        self.bridge.gate = threading.Event()
        self.addCleanup(self.bridge.gate.set)

    def reach_installing(self):
        self.start_download()
        self.cdn.gate.set()
        wait_until(self, lambda: self.ob.status()["phase"] == "installing", what="the installing phase")
        wait_until(self, lambda: bool(self.bridge.chats), what="the first test question reaching the engine")
        wait_until(self, lambda: self.java.service_running, what="the foreground service of the install")

    def finish_install(self):
        self.bridge.gate.set()
        self.assertTrue(self.ob.wait(30), "the worker did not finish")

    def test_the_stop_word_during_the_install_changes_nothing_and_says_why(self):
        self.reach_installing()
        reply = self.ask("ایست")
        self.assertIn(BM.install_not_stoppable_note(), reply)
        self.assertNotIn(HB.emergency_extra(["engine"], False), reply, "the engine was not asked to drop anything")
        self.assertNotIn(HB.emergency_extra([], True), reply, "the notification was not taken away")
        self.assertEqual(self.bridge.cancels, 0, "the first test question of the install must not be cancelled")
        self.assertFalse(self.bridge.gate.is_set())
        self.assertEqual(self.ob.status()["phase"], "installing")
        self.assertTrue(self.java.service_running, "the install goes on, so does its notification")
        self.assertNotIn(("release",), self.java.service_calls)
        self.finish_install()
        self.assertEqual(self.ob.status()["phase"], "ready", "the first test was not harmed")
        wait_until(self, lambda: not self.java.service_running, what="the service to be released when the install is over")

    def test_the_stop_button_of_the_page_during_the_install_is_the_same_word_and_changes_nothing(self):
        """The page's button posts the same word; the lock-free path takes it only while the brain's lock is held by another answer."""
        self.reach_installing()
        reply = self.ask("ایست")
        self.assertIn(BM.install_not_stoppable_note(), reply)
        self.assertEqual(self.bridge.cancels, 0)
        self.assertTrue(self.java.service_running)

    def test_the_notification_button_during_the_install_says_no_and_keeps_the_notification(self):
        import platform_boot
        from brain_hub import service
        self.reach_installing()
        with mock.patch.object(service, "live_hubs", return_value=[self.hub]):
            result = json.loads(platform_boot.emergency_stop())
        self.assertEqual(result, {"ok": False, "hubs": 1, "stopped": [], "released": False},
                         "Java keeps the notification and posts «ایست انجام نشد؛ برنامه را باز کن و «ایست» را بنویس.»")
        self.assertEqual(self.bridge.cancels, 0)
        self.assertEqual(self.ob.status()["phase"], "installing")
        self.assertTrue(self.java.service_running)
        self.finish_install()
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_after_the_install_the_stop_asks_the_engine_again(self):
        self.reach_installing()
        self.finish_install()
        self.assertEqual(self.ob.status()["phase"], "ready")
        wait_until(self, lambda: not self.java.service_running, what="the service to be released")
        reply = self.ask("ایست")
        self.assertGreaterEqual(self.bridge.cancels, 1, "no install is running: the engine is asked as always")
        self.assertIn(HB.emergency_extra(["engine"], False), reply)
        self.assertNotIn(BM.install_not_stoppable_note(), reply)


# ============================================================================ an open question and a body command
class OpenQuestionTests(BodyMixin, OwnBrainApp):
    """A body command is not the answer to an open question: like every other sentence it closes it, and nothing is started or deleted."""

    def test_a_body_command_closes_the_open_download_question_and_nothing_is_fetched(self):
        self.ask("مغز خودت را بگیر")
        self.assertIsNotNone(self.pending_own())
        self.assertIn("چک‌لیستِ دسترسی‌ها", self.ask(HB.ACCESS_ASK))
        self.assertIsNone(self.pending_own())
        self.ask("بله")
        self.nothing_was_fetched()

    def test_a_body_command_closes_the_open_delete_question_and_nothing_is_deleted(self):
        self.install_light()
        self.ask("مغز را پاک کن")
        self.assertEqual(self.pending_own(), "delete")
        self.assertIn("چک‌لیستِ دسترسی‌ها", self.ask(HB.ACCESS_ASK))
        self.ask("بله")
        self.assertEqual(self.ob.status()["phase"], "ready", "the brain is still there")
