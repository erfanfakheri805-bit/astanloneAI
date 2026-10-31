"""
Prompt 958 - the teacher through the real chat.

The Persian brain on a real MemorySystem and a real hub, a fake Android (`FakeJava`) under the native doors. What is proven:

* «از ChatGPT بخواه …» only OPENS a question; nothing leaves the app (no intent, no clipboard) before the user's explicit «بله»;
* a «نه», any other message, or the 30-minute expiry cancels the draft;
* the answer is only read when the user says it arrived; a pack found in it goes through the pack system's own review and its OWN «بله»;
* our own request is never mistaken for the answer; a plain answer is only shown, never run;
* the typing recipe needs the user's per-app allowance, which he can take back; the accessibility page is only OPENED;
* ordinary sentences that merely mention an assistant ("ChatGPT چیه؟") are not commands.
It proves the app's logic against a fake phone; it does not prove how the real ChatGPT / Claude apps behave.
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from native_bridge import facade as native_facade
from persian_brain import hub_state
from teacher import service as teacher_service
from tests import pack_support_prompt958 as S
from tests.native_support_prompt958 import FakeJava
from tests.test_pack_chat_prompt958 import PackChatCase
from tests.test_teacher_prompt958 import install_chat_script

OWN = teacher_service.OWN_PACKAGE
CHATGPT, CLAUDE = "com.openai.chatgpt", "com.anthropic.claude"


def teacher_open(case):
    from persian_brain import hub_teacher
    return hub_teacher.mission_is_open(case.brain, case.hub)


class TeacherChatCase(PackChatCase):
    installed = (CHATGPT, CLAUDE, OWN)

    def setUp(self):
        native_facade.reset_for_tests()
        teacher_service.reset_for_tests()
        self.addCleanup(native_facade.reset_for_tests)
        self.addCleanup(teacher_service.reset_for_tests)
        self.jvm = FakeJava(installed=set(self.installed), package=CHATGPT)
        native_facade.set_jvm(self.jvm)
        super().setUp()

    # ------------------------------------------------------------------ helpers
    def svc(self):
        return teacher_service.get_service(self.hub)

    def latest(self):
        return self.svc().store.latest(only_open=False)

    def inbox(self):
        return self.hub.inbox_dir()

    def ask_and_confirm(self, sentence="از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه"):
        question = self.say(sentence)
        self.assertEqual(self.pending()[0], "teacher_send", question)
        return question, self.say("بله")

    def kind(self):
        return self.trace_kind()[1]


class AskTests(TeacherChatCase):
    def test_asking_only_opens_a_question_nothing_leaves_before_the_yes(self):
        reply = self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.assertIn("بفرستم؟ (بله / نه)", reply)
        self.assertIn("ChatGPT", reply)
        self.assertIn("ساخت عکس", reply)
        self.assertIn("بدون «بله»ی تو چیزی نصب یا فعال نمی‌شود", reply)
        self.assertEqual(self.pending()[0], "teacher_send")
        self.assertEqual(self.jvm.started, [])
        self.assertIsNone(self.jvm.clipboard)
        self.assertEqual(self.latest()["state"], "drafted")
        self.assertEqual(self.latest()["assistant"], "chatgpt")

    def test_the_yes_sends_through_the_share_sheet_and_keeps_a_copy_on_the_clipboard(self):
        _question, sent = self.ask_and_confirm()
        self.assertIn("اشتراک‌گذاری", sent)
        self.assertIn("جواب آمد", sent)
        self.assertTrue(self.jvm.started)
        self.assertIsNotNone(self.jvm.clipboard)
        self.assertIn("ساخت عکس", self.jvm.clipboard)
        self.assertEqual(self.latest()["state"], "sent")
        self.assertEqual(self.latest()["route"], "share")
        self.assertIsNone(self.pending())

    def test_a_no_cancels_the_draft(self):
        self.say("از Claude بخواه یه قابلیت ساخت عکس برام بسازه")
        self.assertIn("چیزی فرستاده نشد", self.say("نه"))
        self.assertEqual(self.latest()["state"], "cancelled")
        self.assertEqual(self.jvm.started, [])
        self.assertIsNone(self.jvm.clipboard)

    def test_any_other_message_withdraws_the_question_and_the_draft(self):
        self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.say("امروز هوا خوب است")
        self.assertIsNone(self.pending())
        self.assertEqual(self.latest()["state"], "cancelled")
        self.assertIsNone(self.say("بله") if self.pending() else None)
        self.assertEqual(self.jvm.started, [])

    def test_the_question_expires_after_half_an_hour(self):
        self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.clock.advance(31 * 60)
        reply = self.say("بله")
        self.assertIn("فرستادن درخواست به دستیار بیرونی", reply)
        self.assertIn("منقضی", reply)
        self.assertEqual(self.jvm.started, [])
        self.assertEqual(self.latest()["state"], "cancelled")

    def test_an_assistant_that_is_not_installed_goes_through_the_website(self):
        reply = self.say("از جمینای بپرس تفاوت HTTP و HTTPS چیه؟")
        self.assertIn("دیده نمی‌شود", reply)
        self.assertIn("gemini.google.com", reply)
        sent = self.say("بله")
        self.assertIn("سایت", sent)
        self.assertEqual(self.latest()["route"], "site")
        self.assertIn("HTTPS", self.jvm.clipboard)
        self.assertTrue(any(getattr(i, "action", "") == "VIEW" for i in self.jvm.started))

    def test_the_sentence_after_a_gap_reply_uses_the_remembered_wish(self):
        hub_state.save_wish(self.memory, "یه عکس از گربه برام بساز", self.clock)
        reply = self.say("از ChatGPT بخواه")
        self.assertIn("درخواست قبلی‌ات را برمی‌دارم", reply)
        self.assertIn("گربه", reply)
        self.assertEqual(self.pending()[0], "teacher_send")

    def test_without_any_wish_the_app_asks_what_to_request(self):
        reply = self.say("از Claude بخواه")
        self.assertIn("چه چیزی را از", reply)
        self.assertIsNone(self.pending())

    def test_a_new_request_replaces_an_open_mission_only_after_the_yes(self):
        self.ask_and_confirm("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        first = self.latest()["id"]
        reply = self.say("از Claude بخواه یه ماشین‌حساب برام بسازه")
        self.assertIn("ماموریت بازِ قبلی با «بله» کنار گذاشته می‌شود", reply)
        self.assertEqual(self.svc().store.get(first)["state"], "sent")          # nothing changed before the yes
        self.say("بله")
        self.assertEqual(self.svc().store.get(first)["state"], "cancelled")
        self.assertEqual(self.latest()["assistant"], "claude")

    def test_not_on_a_phone_the_failure_is_said_and_the_manual_way_is_offered(self):
        native_facade.set_jvm(None)                         # no Android here: the null bridge
        native_facade.reset_for_tests()
        self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        reply = self.say("بله")
        self.assertIn("نتوانستم", reply)
        self.assertIn("چیزی جایی نرفت", reply)
        self.assertIn("راه دستی", reply)
        self.assertEqual(self.latest()["state"], "failed")


class AnswerTests(TeacherChatCase):
    def test_a_pack_in_the_clipboard_is_reviewed_and_installed_only_after_a_second_yes(self):
        self.ask_and_confirm()
        self.jvm.clipboard = S.lang_pack(pid="fa_teacher")
        reply = self.say("جواب آمد")
        self.assertIn("فقط بررسی کردم", reply)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", reply)
        self.assertEqual(self.pending()[0], "pack_install")
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.latest()["state"], "proposed")
        self.assertIn("نصب و فعال شد", self.say("بله"))
        self.assertEqual(self.say("پایتخت ایران کجاست؟"), "تهران")

    def test_our_own_request_is_never_taken_for_the_answer(self):
        self.ask_and_confirm()
        reply = self.say("جواب آمد")                          # the clipboard still holds OUR request
        self.assertIn("جوابی", reply)
        self.assertIn("همان درخواستِ خودِ ما", reply)
        self.assertEqual(self.latest()["state"], "sent")
        self.assertIsNone(self.pending())

    def test_a_text_without_a_pack_is_not_taken_for_a_code_request(self):
        self.ask_and_confirm()
        self.jvm.clipboard = "ببخشید، نمی‌توانم این کار را انجام بدهم."
        reply = self.say("جواب آمد")
        self.assertIn("بستهٔ کامل", reply)
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.latest()["state"], "sent")

    def test_a_text_shared_into_the_app_is_read_and_retired(self):
        self.ask_and_confirm()
        os.makedirs(self.inbox(), exist_ok=True)
        path = os.path.join(self.inbox(), "shared_1.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(S.lang_pack(pid="fa_shared"))
        os.utime(path, (self.clock() + 5, self.clock() + 5))
        self.jvm.clipboard = None
        reply = self.say("جواب آمد")
        self.assertIn("از متنی که به این برنامه اشتراک‌گذاری کردی", reply)
        self.assertEqual(self.pending()[0], "pack_install")
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(self.inbox(), "done_shared_1.txt")))

    def test_a_plain_question_gets_a_plain_answer_that_is_only_shown(self):
        self.ask_and_confirm("از ChatGPT بپرس تفاوت HTTP و HTTPS چیه؟")
        self.assertEqual(self.latest()["kind"], "ask")
        self.jvm.clipboard = "HTTPS همان HTTP است که با TLS رمزنگاری می‌شود.\nimport os; os.system('x')"
        reply = self.say("جواب آمد")
        self.assertIn("رمزنگاری", reply)
        self.assertIn("درستی‌اش را من نسنجیده‌ام", reply)
        self.assertEqual(self.latest()["state"], "done")
        self.assertIn("رمزنگاری", self.latest()["answer"])
        self.assertIsNone(self.pending())

    def test_a_pack_that_fails_the_scan_is_explained_and_nothing_is_installed(self):
        self.ask_and_confirm()
        bad = S.text_pack(pid="demo_bad", source="import os\n\ndef register(api):\n    os.system('x')\n")
        self.jvm.clipboard = bad
        reply = self.say("جواب آمد")
        self.assertIn("نپذیرفتم", reply)
        self.assertEqual(self.pm().list(), [])
        self.assertIsNone(self.pending())
        self.assertEqual(self.latest()["state"], "failed")

    def test_an_arrival_with_no_open_mission_is_just_an_ordinary_sentence(self):
        self.assertIsNone(self.say("جواب آمد"))
        self.assertNotEqual(self.trace_kind()[0], "HUB")
        self.assertIsNone(self.svc().store.latest(only_open=False))
        # Updated in Prompt 958 on purpose: with no open mission «خودت انجام بده» is still not a command (nothing starts, nothing is asked), but the
        # brain no longer stays silent for a request it cannot place: it says it does not know and names the ways to grow.
        reply = self.say("خودت انجام بده")
        self.assertIn("نمی‌دانم", reply)
        self.assertNotEqual(self.trace_kind()[0], "HUB")
        self.assertIsNone(self.svc().store.latest(only_open=False))
        self.assertIsNone(self.pending())

    def test_a_drafted_but_unsent_mission_does_not_make_the_arrival_a_command(self):
        self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")      # the question is open, nothing was sent
        self.assertEqual(self.latest()["state"], "drafted")
        self.assertFalse(teacher_open(self))

    def test_a_mission_cancelled_behind_the_questions_back_is_not_sent(self):
        self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.svc().cancel()                                                # some other path cancelled it
        reply = self.say("بله")
        self.assertIn("دیگر باز نیست", reply)
        self.assertEqual(self.jvm.started, [])
        self.assertIsNone(self.jvm.clipboard)

    def test_the_arrival_is_not_a_command_after_the_mission_is_finished(self):
        self.ask_and_confirm("از ChatGPT بپرس تفاوت HTTP و HTTPS چیه؟")
        self.jvm.clipboard = "HTTPS با TLS رمزنگاری می‌شود."
        self.say("جواب آمد")
        self.assertEqual(self.latest()["state"], "done")
        self.say("جواب آمد")
        self.assertEqual(self.latest()["state"], "done")
        self.assertEqual(len(self.svc().store.missions()), 1)


class StatusCancelListTests(TeacherChatCase):
    def test_status_cancel_and_the_arrival_afterwards(self):
        self.assertIn("ماموریتی با دستیار بیرونی ندارم", self.say("وضعیت ماموریت"))
        self.ask_and_confirm()
        status = self.say("وضعیت ماموریت")
        self.assertIn("ChatGPT", status)
        self.assertIn("فرستاده شد؛ منتظر جواب", status)
        self.assertIn("اشتراک‌گذاری", status)
        self.assertIn("لغو کردم", self.say("ماموریت را لغو کن"))
        self.assertEqual(self.latest()["state"], "cancelled")
        self.assertIn("ماموریت بازی نبود", self.say("ماموریت را لغو کن"))
        self.jvm.clipboard = S.lang_pack(pid="fa_late")
        self.assertIsNone(self.say("جواب آمد"))                              # after the cancel the arrival is no command any more
        self.assertEqual(self.pm().list(), [])

    def test_the_list_of_assistants_says_which_ones_the_phone_shows(self):
        reply = self.say("کدام دستیارهای بیرونی نصب است؟")
        self.assertIn("ChatGPT — برنامه‌اش روی گوشی دیده می‌شود", reply.replace("\u2066", "").replace("\u2069", ""))
        self.assertIn("Gemini", reply)
        self.assertIn("دیده نمی‌شود", reply)

    def test_sentences_that_only_mention_an_assistant_are_not_commands(self):
        for sentence in ("ChatGPT چیه؟", "چت جی بی تی بهتره یا کلود؟", "از ChatGPT چی میدونی؟", "یک متن شبیه ChatGPT بنویس"):
            self.say(sentence)
            self.assertIsNone(self.pending(), sentence)
            self.assertFalse((self.trace_kind()[1] or "").startswith("teacher"), sentence)
        self.assertIsNone(self.svc().store.latest(only_open=False))


class ScreenTests(TeacherChatCase):
    ANSWER = S.lang_pack(pid="fa_screen")

    def setUp(self):
        super().setUp()
        self.state = install_chat_script(self.jvm, self.ANSWER)
        self.jvm.classes["com.erfan.standaloneai.PyAccessibilityService"].isConnected = staticmethod(lambda: True)
        mono = [0.0]

        def sleep(seconds):
            mono[0] += seconds
        teacher_service.reset_for_tests()
        root = os.fspath(self.hub.root)
        service = teacher_service.TeacherService(root, registry=None, hub=self.hub, clock=self.clock, sleep=sleep, monotonic=lambda: mono[0],
                                                 run_async=False)
        service.install_allow_provider()
        teacher_service._SERVICES[root] = service

    def test_the_run_needs_the_users_allowance_and_then_reads_the_answer(self):
        self.ask_and_confirm()
        asked = self.say("خودت انجام بده")
        self.assertIn("اجازه می‌دهی؟ (بله / نه)", asked)
        self.assertIn(CHATGPT, asked)
        self.assertEqual(self.pending()[0], "teacher_screen")
        self.assertEqual(self.svc().allowed_apps(), [])                    # nothing allowed before the yes
        started = self.say("بله")
        self.assertIn("اجازه ثبت شد", started)
        self.assertIn("شروع کردم", started)
        self.assertEqual([p for p, _ in self.svc().allowed_apps()], [CHATGPT])
        self.assertEqual(self.latest()["state"], "captured")
        reply = self.say("جواب آمد")
        self.assertIn("از صفحهٔ برنامهٔ دستیار", reply)
        self.assertEqual(self.pending()[0], "pack_install")
        self.assertEqual(self.pm().list(), [])

    def test_a_no_leaves_the_app_untouched(self):
        self.ask_and_confirm()
        self.say("خودت انجام بده")
        self.assertIn("چیزی تغییر نکرد", self.say("نه"))
        self.assertEqual(self.svc().allowed_apps(), [])
        self.assertEqual(self.state["typed"], "")

    def test_the_user_takes_the_allowance_back(self):
        self.ask_and_confirm()
        self.say("خودت انجام بده")
        self.say("بله")
        self.assertTrue(self.svc().allowed_apps())
        self.assertIn("پس گرفته شد", self.say("به برنامه‌های دیگه سر نزن"))
        self.assertEqual(self.svc().allowed_apps(), [])

    def test_with_the_service_off_the_app_points_to_the_settings_page_and_asks_nothing(self):
        self.jvm.classes["com.erfan.standaloneai.PyAccessibilityService"].isConnected = staticmethod(lambda: False)
        self.ask_and_confirm()
        reply = self.say("خودت انجام بده")
        self.assertIn("روشن‌کردنش فقط کار خودت است", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.svc().allowed_apps(), [])

    def test_without_an_open_mission_the_phrase_is_not_a_command(self):
        reply = self.say("خودت انجام بده")
        self.assertNotIn("اجازه می‌دهی", reply or "")
        self.assertIsNone(self.pending())

    def test_the_accessibility_page_is_only_opened(self):
        reply = self.say("تنظیمات دسترس‌پذیری را باز کن")
        self.assertIn("فقط خودت می‌توانی بزنی", reply)
        self.assertTrue(self.jvm.started)
        self.assertIsNone(self.pending())


if __name__ == "__main__":
    unittest.main()
