"""Prompt 959 (stage A) - the answer memory IN THE CHAT: the real Persian brain on a real memory and hub, a scripted provider.

The user's terms: an answer the cloud brain gave once may be given again WITHOUT the internet - but only for a general question,
only when it is clearly said, never for anything personal, secret or "of today", and the user can switch it off, wipe it, or tell
the app that an answer was wrong. «این جواب غلط بود» must still reach the older feedback handling whenever the last reply was not
one of these answers.
"""
import json
import os
import stat
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain import hub_brain_commands as BC
from persian_brain import hub_messages_brain as BM
from persian_brain import normalization as nz
from self_builder import fa_text
from tests.test_brain_v2_chat_prompt959 import CloudChatCase
from tests.test_brain_v2_core_prompt959 import JSON, KEY, openai_answer

Q1 = "پایتخت فرانسه کجاست؟"
Q2 = "چرا آسمان آبی است؟"
Q3 = "فاصله زمین تا ماه چقدر است؟"
A1 = "پایتخت فرانسه پاریس است."
A2 = "به‌خاطر پراکندگی نور آبی در جو."
A3 = "حدود ۳۸۴ هزار کیلومتر."


class MemoryChatCase(CloudChatCase):
    def setUp(self):
        super().setUp()
        self.connect(memory=True)
        self.cloud.calls.clear()
        self.answers(A1)

    def answers(self, *texts):
        self.cloud.script = [(200, openai_answer(t), JSON) for t in texts]

    def asked(self):
        return len(self.cloud.calls)

    def file_text(self):
        with open(os.path.join(self.brain_dir(), "learned.json"), encoding="utf-8") as handle:
            return handle.read()


class KeepAndRecallTests(MemoryChatCase):
    def test_the_second_asking_is_answered_offline_and_says_so(self):
        first = self.say(Q1)
        self.assertTrue(first.startswith(A1))
        self.assertIn("نگه داشتم", first, "the first kept answer comes with a one-time note")
        self.assertEqual(self.asked(), 1)
        second = self.say(Q1)
        self.assertEqual(self.asked(), 1, "no second request: the answer came from the phone")
        self.assertTrue(second.startswith(A1))
        self.assertIn("بدون اینترنت از حافظهٔ خودم", second)
        self.assertIn("همین الان", second)
        self.assertIn("این جواب غلط بود", second)
        self.assertNotIn("نگه داشتم", second, "the one-time note is not repeated")
        self.assertEqual(self.trace_kind(), ("CLOUD", "answer"))

    def test_the_note_is_shown_once_only(self):
        self.answers(A1, A2)
        self.assertIn("نگه داشتم", self.say(Q1))
        second = self.say(Q2)
        self.assertTrue(second.startswith(A2))
        self.assertNotIn("نگه داشتم", second)
        self.assertEqual(self.svc.learned.count(), 2)
        self.assertTrue(self.svc.settings.get()["kept_note"])

    def test_the_age_is_told(self):
        self.say(Q1)
        self.clock.advance(3 * 3600)
        self.assertIn("۳ ساعت پیش", self.say(Q1))
        self.clock.advance(2 * 86400)
        self.assertIn("روز پیش", self.say(Q1))

    def test_only_polite_filler_may_differ(self):
        self.say(Q1)
        again = self.say("لطفا " + Q1)
        self.assertTrue(again.startswith(A1))
        self.assertIn("تعارفی", again)
        self.assertEqual(self.asked(), 1)
        self.answers(A1, A3)
        other = self.say("پایتخت ایتالیا کجاست؟")
        self.assertEqual(self.asked(), 2, "another question goes to the cloud")
        self.assertNotIn("حافظهٔ خودم", other)

    def test_a_changed_number_or_a_negation_is_another_question(self):
        self.answers("هشت سیاره.", "نه سیاره.", "هیچ.")
        self.say("چند سیاره در منظومه شمسی وجود دارد؟")
        self.say("چند سیاره در منظومه شمسی ۹ وجود دارد؟")
        self.say("چند سیاره در منظومه شمسی وجود ندارد؟")
        self.assertEqual(self.asked(), 3)

    def test_it_works_with_the_internet_switch_off_and_with_the_brain_switched_off(self):
        self.say(Q1)
        self.say("اینترنت را خاموش کن")
        offline = self.say(Q1)
        self.assertEqual(self.asked(), 1)
        self.assertIn("حافظهٔ خودم", offline)
        reply = self.say(Q2)
        self.assertEqual(self.asked(), 1, "a NEW question cannot be answered without the internet")
        self.assertNotIn(A2, reply or "")
        self.say("اینترنت را روشن کن")
        self.say("مغز ابری را خاموش کن")
        self.assertIn("حافظهٔ خودم", self.say(Q1))
        self.assertEqual(self.asked(), 1)

    def test_it_survives_an_app_restart(self):
        self.say(Q1)
        self.open_app()
        self.assertIn("حافظهٔ خودم", self.say(Q1))
        self.assertEqual(self.asked(), 1)

    def test_a_kept_answer_is_still_there_when_the_provider_fails(self):
        self.say(Q1)
        self.cloud.script = [(503, b"{}", JSON)]
        self.assertTrue(self.say(Q1).startswith(A1))
        self.assertIn("مشکل موقت", self.say(Q2), "a question that was never kept still gets the honest failure")

    def test_a_memory_answer_gives_a_follow_up_its_context(self):
        self.answers(A1, A2, "حدود ۲ میلیون نفر.")
        self.say(Q1)
        self.say(Q2)
        self.say(Q1)                                      # from the memory: it is now the newest exchange of the conversation
        self.assertEqual(self.asked(), 2)
        self.say("جمعیت آن شهر چقدر است؟")
        sent = json.loads(self.cloud.calls[-1].body.decode("utf-8"))["messages"]
        self.assertEqual([(m["role"], m["content"]) for m in sent][-3:],
                         [("user", Q1), ("assistant", A1), ("user", "جمعیت آن شهر چقدر است؟")])

    def test_asking_the_same_thing_twice_does_not_fill_the_history_with_copies(self):
        self.say(Q1)
        self.say(Q1)
        self.say(Q1)
        self.assertEqual(self.svc.history.count(), 1)


class WhatIsNeverKeptTests(MemoryChatCase):
    def test_questions_of_today_or_with_a_follow_up_or_requests_to_write_are_asked_again_every_time(self):
        for question in ("قیمت طلا امروز چقدر است؟", "هوای اصفهان الان چطور است؟", "جمعیت آن شهر چقدر است؟", "یک شعر کوتاه دربارهٔ بهار بنویس"):
            with self.subTest(question=question):
                before = self.asked()
                self.say(question)
                self.say(question)
                self.assertEqual(self.asked() - before, 2, "asked twice, answered by the cloud twice")
        self.assertEqual(self.svc.learned.count(), 0)
        self.assertFalse(os.path.exists(os.path.join(self.brain_dir(), "learned.json")))
        self.assertFalse(self.svc.settings.get()["kept_note"], "nothing was kept, so no note")

    def test_an_answer_cut_by_the_length_limit_is_not_kept(self):
        self.cloud.script = [(200, openai_answer("پاسخ ناتمام", finish="length"), JSON)]
        first = self.say(Q2)
        self.assertIn("ناتمام ماند", first)
        self.assertNotIn("نگه داشتم", first)
        self.say(Q2)
        self.assertEqual(self.asked(), 2)

    def test_an_apology_or_a_counter_question_is_not_kept(self):
        for answer in ("متاسفم، نمی‌توانم به این سؤال جواب بدهم.", "منظورتان دقیقاً چیست؟"):
            with self.subTest(answer=answer):
                self.answers(answer)
                before = self.asked()
                self.say(Q3)
                self.say(Q3)
                self.assertEqual(self.asked() - before, 2)
        self.assertEqual(self.svc.learned.count(), 0)

    def test_a_question_with_personal_details_is_sent_only_when_allowed_and_never_kept(self):
        self.say("اطلاعات شخصی را هم برای مغز ابری بفرست")
        self.assertTrue(self.svc.status()["share_private"])
        question = "ایمیل من test@example.com است چرا پیام‌هایم اسپم می‌شود؟"
        self.answers("چون فیلتر اسپم دارد.")
        before = self.asked()
        self.say(question)
        self.say(question)
        self.assertEqual(self.asked() - before, 2)
        self.assertEqual(self.svc.learned.count(), 0)

    def test_the_file_never_holds_a_key_a_secret_or_the_pasted_text(self):
        self.say(Q1)
        text = self.file_text()
        self.assertNotIn(KEY, text)
        self.assertNotIn("AIza", text)
        doc = json.loads(text)
        self.assertEqual(len(doc["items"]), 1)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.brain_dir(), "learned.json")).st_mode), 0o600)
        self.say(Q1)
        lines = [e for e in self.hub.audit.entries() if e["kind"].startswith("brain.memory")]
        self.assertEqual([e["kind"] for e in lines], ["brain.memory_kept", "brain.memory_hit"])
        audit = json.dumps(self.hub.audit.entries(), ensure_ascii=False)
        self.assertNotIn(A1, audit, "the audit line says a memory event happened, never what it was")
        self.assertNotIn("فرانسه", audit)
        self.assertTrue(self.hub.audit.verify()["ok"])


class CommandTests(MemoryChatCase):
    def test_status_counts_the_kept_answers(self):
        self.say(Q1)
        reply = self.say("چند جواب نگه داشته‌ای؟")
        self.assertIn("۱ از حداکثر ۲۰۰", reply)
        self.assertIn("روشن", reply)
        self.assertEqual(self.asked(), 1, "a command never reaches the cloud")
        self.assertIn("جواب‌های نگه‌داشته‌شده برای استفادهٔ آفلاین: ۱", self.say("وضعیت مغز ابری"))

    def test_switching_the_keeping_off_stops_keeping_and_stops_answering_from_the_memory(self):
        self.say(Q1)
        off = self.say("نگه‌داشتن جواب‌ها را خاموش کن")
        self.assertIn("خاموش شد", off)
        self.assertIn("۱ جواب قبلی هنوز روی گوشی است", off)
        self.assertFalse(self.svc.status()["memory_on"])
        self.answers(A1, A2)
        self.say(Q1)
        self.assertEqual(self.asked(), 2, "while it is off the old answer is not used either")
        self.say(Q2)
        self.say(Q2)
        self.assertEqual(self.asked(), 4)
        self.assertEqual(self.svc.learned.count(), 1, "nothing new was kept")
        on = self.say("نگه‌داشتن جواب‌ها را روشن کن")
        self.assertIn("نگه داشته می‌شود", on)
        self.say(Q2)
        self.say(Q2)
        self.assertEqual(self.asked(), 5)
        self.assertEqual(self.svc.learned.count(), 2)

    def test_wiping_removes_every_kept_answer_and_the_file(self):
        self.answers(A1, A2)
        self.say(Q1)
        self.say(Q2)
        self.assertEqual(self.svc.learned.count(), 2)
        reply = self.say("جواب‌های نگه‌داشته‌شده را پاک کن")
        self.assertIn("۲ جواب نگه‌داشته‌شده از گوشی حذف شد", reply)
        self.assertFalse(os.path.exists(os.path.join(self.brain_dir(), "learned.json")))
        self.say(Q1)
        self.assertEqual(self.asked(), 3, "after the wipe the cloud is asked again")
        self.assertEqual(self.svc.learned.count(), 1, "and it is kept again")
        self.assertIn("۱ جواب نگه‌داشته‌شده از گوشی حذف شد", self.say("حافظهٔ جواب‌ها را پاک کن"))
        self.assertIn("جواب نگه‌داشته‌شده‌ای نبود", self.say("پاسخ‌های ذخیره‌شده را پاک کن"))

    def test_forgetting_the_key_leaves_the_kept_answers_and_says_so(self):
        self.say(Q1)
        ask = self.say("کلید را فراموش کن")
        self.assertIn("می‌مانند", ask)
        done = self.say("بله")
        self.assertIn("کلید پاک شد", done)
        self.assertIn("۱ جواب نگه‌داشته‌شده هنوز روی گوشی است", done)
        self.assertFalse(self.svc.vault.exists())
        again = self.say(Q1)
        self.assertIn("حافظهٔ خودم", again, "kept answers are the user's own data: they stay until he wipes them")
        self.assertEqual(self.asked(), 1)

    def test_the_emergency_stop_also_stops_the_memory_until_resumed(self):
        self.say(Q1)
        self.say("ایست")
        self.assertIn("ایست دادی", self.say(Q1))
        self.assertEqual(self.asked(), 1)
        self.say("ادامه")
        self.assertIn("حافظهٔ خودم", self.say(Q1))

    def test_unrelated_sentences_are_not_taken_for_memory_commands(self):
        self.say(Q1)
        for text in ("جواب سؤال من را ذخیره کن", "جواب این سؤال چیه", "چه جواب‌هایی بلدی؟", "حافظه ات را پاک کن", "این جواب را یاد بگیر"):
            with self.subTest(text=text):
                self.say(text)
                self.assertEqual(self.svc.learned.count(), 1, text)
                self.assertTrue(self.svc.status()["memory_on"], text)
                self.assertNotEqual(self.trace_kind()[1], "brain_mem_clear", text)


class WrongAnswerTests(MemoryChatCase):
    def test_wrong_after_a_remembered_answer_forgets_it(self):
        self.say(Q1)
        self.say(Q1)                                       # from the memory
        reply = self.say("این جواب غلط بود")
        self.assertIn("از حافظه‌ام پاک کردم", reply)
        self.assertEqual(self.trace_kind(), ("HUB", "brain_wrong"))
        self.assertEqual(self.svc.learned.count(), 0)
        self.say(Q1)
        self.assertEqual(self.asked(), 2, "asked again, the cloud answers again")

    def test_wrong_right_after_a_fresh_cloud_answer_forgets_that_one_too(self):
        self.say(Q1)
        self.assertIn("از حافظه‌ام پاک کردم", self.say("جواب غلط بود"))
        self.assertEqual(self.svc.learned.count(), 0)

    def test_wrong_after_an_answer_that_was_never_kept_says_so(self):
        self.say("قیمت طلا امروز چقدر است؟")
        reply = self.say("جواب غلط بود")
        self.assertIn("نگه نداشته بودم", reply)
        self.assertEqual(self.trace_kind(), ("HUB", "brain_wrong"))

    def test_wrong_after_any_other_reply_is_the_old_feedback_handling_and_forgets_nothing(self):
        self.say(Q1)
        self.say("سلام")
        reply = self.say("جواب غلط بود")
        self.assertNotIn("حافظه‌ام", reply or "")
        self.assertEqual(self.trace_kind()[0], "FEEDBACK")
        self.assertEqual(self.svc.learned.count(), 1)

    def test_wrong_with_no_brain_answer_before_it_is_the_old_feedback_handling(self):
        reply = self.say("جواب غلط بود")
        self.assertEqual(self.trace_kind()[0], "FEEDBACK")
        self.assertNotIn("حافظه‌ام", reply or "")
        self.assertEqual(self.asked(), 0)

    def test_wrong_is_taken_only_once_per_answer(self):
        self.say(Q1)
        self.say("جواب غلط بود")
        again = self.say("جواب غلط بود")
        self.assertEqual(self.trace_kind()[0], "FEEDBACK", "the second «wrong» has no brain answer before it any more")
        self.assertNotIn("حافظه‌ام", again or "")

    def test_an_old_answer_is_not_blamed_a_day_later(self):
        self.say(Q1)
        self.clock.advance(25 * 3600)
        self.say("جواب غلط بود")
        self.assertEqual(self.trace_kind()[0], "FEEDBACK")
        self.assertEqual(self.svc.learned.count(), 1)

    def test_praise_is_never_taken_as_a_complaint(self):
        self.say(Q1)
        self.say("آفرین")
        self.assertEqual(self.svc.learned.count(), 1)
        self.assertEqual(self.trace_kind()[0], "FEEDBACK")

    def test_wrong_while_the_brain_was_never_used_does_not_touch_the_cloud_files(self):
        self.svc.clear_learned()
        self.say("جواب غلط بود")
        self.assertFalse(os.path.exists(os.path.join(self.brain_dir(), "learned.json")))


class SuggestedCommandsTests(unittest.TestCase):
    """The app tells the user which words to say. Each such phrase must really be understood (a hint that does not work is a bug:
    the first version of the «personal details» hint was one)."""

    def test_every_command_the_texts_suggest_is_understood_as_that_command(self):
        table = (
            (BM.setup_done(False), "تاریخچهٔ مغز ابری را پاک کن", BC.HISTORY_CLEAR),
            (BM.setup_done(False), "جواب‌های نگه‌داشته‌شده را پاک کن", BC.MEM_CLEAR),
            (BM.setup_done(False), "نگه‌داشتن جواب‌ها را خاموش کن", BC.MEM_OFF),
            (BM.setup_done(False), "کلید را فراموش کن", BC.FORGET_KEY),
            (BM.setup_done(False), "مغز ابری را خاموش کن", BC.OFF),
            (BM.setup_done(False), "مغز ابری را روشن کن", BC.SETUP),
            (BM.setup_done(False), "وضعیت مغز ابری", BC.STATUS),
            (BM.blocked("email", "ایمیل", False), "اطلاعات شخصی را هم برای مغز ابری بفرست", BC.PRIVATE_ON),
            (BM.kept_first_note(), "نگه‌داشتن جواب‌ها را خاموش کن", BC.MEM_OFF),
            (BM.kept_first_note(), "جواب‌های نگه‌داشته‌شده را پاک کن", BC.MEM_CLEAR),
            (BM.turned_off(), "مغز ابری را روشن کن", BC.SETUP),
            (BM.forgotten(True, 2), "جواب‌های نگه‌داشته‌شده را پاک کن", BC.MEM_CLEAR),
            (BM.memory_off_done(2), "جواب‌های نگه‌داشته‌شده را پاک کن", BC.MEM_CLEAR),
            (BM.memory_status({"learned": 1, "memory_on": True}), "نگه‌داشتن جواب‌ها را روشن کن", BC.MEM_ON),
            (BM.key_check_failed("x", "", False), "مغز ابری را امتحان کن", BC.PROBE),
            (BM.model_missing(), "مدل مغز ابری را gemini-3.8-flash کن", BC.MODEL),
        )
        for text, phrase, kind in table:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, "the phrase is really suggested by this text")
                norm = nz.normalize(phrase)
                command = BC.classify(phrase, norm, fa_text.words(norm))
                self.assertIsNotNone(command, phrase)
                self.assertEqual(command.kind, kind)


if __name__ == "__main__":
    unittest.main()
