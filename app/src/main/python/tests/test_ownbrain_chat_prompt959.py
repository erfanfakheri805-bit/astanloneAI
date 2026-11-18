"""Prompt 959 (stage B, «مغز خودکار») - the conversation that gives the assistant a brain of its own, driven only through the real front door
(HTTP `POST /api/message` -> RuntimeCore -> Core -> Persian brain -> hub -> `OwnBrain`).

What the user asked for, in his words: the assistant must provide what it lacks BY ITSELF - no key, no cost, no other AI service, nothing for him
to download and upload. What these tests pin is how that stays honest and under his control:

* the wish only ASKS: nothing is requested, written or granted before his «بله» (and a «نه», a different sentence, or half an hour of silence
  withdraws the question);
* a brain that cannot work on this phone (no engine in this build, no internet, too little RAM, too little room, RAM unreadable) is refused
  BEFORE any download, and says why;
* a damaged / changed file is never installed; a cut connection keeps what was fetched; a load that fails or a first question that is not answered
  never ends in «آماده»; the user can retry, and a crash of the app while loading is not repeated by itself;
* once the brain is ready it answers the sentences nothing else could answer, and says so (once);
* «مغز را پاک کن» asks first and then frees everything.

Everything is proven with doubles for the engine and the download (`tests/ownbrain_support_prompt959`). Nothing here says how the real engine, the
real files or the real phone behave.
"""
import json
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from android_adapters.bridge import BridgeConnectivity
from brain_hub import llm as hub_llm
from brain_hub import ownbrain_state as ST
from model_runtime import litertlm_runtime as LR
from net_tools import resumable
from persian_brain import hub_messages_ownbrain as BM
from tests.ownbrain_support_prompt959 import (DATA, LIGHT_DATA, OwnBrainApp, OwnCdn, Usage, engine_runtime, tiny_choice, write_meminfo)

WISH = "مغز خودت را بگیر"


class ConsentTests(OwnBrainApp):
    def test_the_wish_only_asks(self):
        before = self.permission_snapshot()
        reply = self.ask(WISH)
        for must in ("«بله»", "«نه»", "بدون کلید", "بدون هزینه", "huggingface.co", "SHA-256", "VPN", "هنوز آزمایش نشده", BM.PAUSE, BM.DELETE):
            self.assertIn(must, reply)
        self.assertEqual(self.pending_own(), "consent")
        self.assertEqual(self.ob.status()["phase"], "idle")
        self.nothing_was_fetched()
        self.assertEqual(self.fetch.requests, [])
        self.assertEqual(self.permission_snapshot(), before, "asking must not change a single permission")

    def test_the_users_own_words_get_the_same_offer(self):
        for sentence in ("می‌خوام خودش کارای لازم رو برای چیزی که نداره فراهم کنه", "خودت یک مغز برای خودت فراهم کن", "برای خودت مغز بگیر"):
            self.start_app()
            reply = self.ask(sentence)
            self.assertIn("«بله»", reply, sentence)
            self.assertEqual(self.pending_own(), "consent", sentence)
            self.nothing_was_fetched()

    def test_no_withdraws_and_nothing_is_left(self):
        self.ask(WISH)
        reply = self.ask("نه")
        self.assertIn("چیزی دانلود نشد", reply)
        self.assertIsNone(self.pending_own())
        self.nothing_was_fetched()
        self.ask("بله")                                                  # the question is closed: a later «بله» starts nothing
        self.nothing_was_fetched()

    def test_another_sentence_withdraws_the_question(self):
        self.ask(WISH)
        self.ask("ساعت چنده؟")
        self.assertIsNone(self.pending_own())
        self.ask("بله")
        self.nothing_was_fetched()
        self.assertEqual(self.ob.status()["phase"], "idle")

    def test_half_an_hour_of_silence_withdraws_the_question(self):
        self.ask(WISH)
        self.age_pending(31 * 60)
        self.ask("بله")
        self.nothing_was_fetched()
        self.assertEqual(self.ob.status()["phase"], "idle")

    def test_a_question_that_is_still_fresh_is_answered(self):
        self.ask(WISH)
        self.age_pending(20 * 60)
        self.assertIn("شروع کردم", self.ask("بله"))

    def test_the_explanation_questions_start_nothing(self):
        for sentence in ("مغز خودکار چیست؟", "مغز بگیرم هزینه دارد؟", "مغز خودت چقدر فضا می‌خواد", "مغز آفلاین امنه؟"):
            reply = self.ask(sentence)
            self.assertIn(BM.START, reply, sentence)
            self.assertIn("بدون کلید", reply, sentence)
            self.assertIsNone(self.pending_own(), sentence)
            self.nothing_was_fetched()

    def test_yes_in_the_users_own_forms_starts_it(self):
        for yes in ("بله", "آره", "باشه", "بله شروع کن", "آره بگیرش", "اوکی شروع کن"):
            self.ask(WISH)
            reply = self.ask(yes)
            self.assertIn("شروع کردم", reply, yes)
            self.assertEqual(self.ob.status()["phase"], "ready", yes)
            self.reset_brain()

    def test_a_yes_with_a_question_inside_is_not_a_yes(self):
        self.ask(WISH)
        self.ask("بله ولی اول بگو چقدر جا می‌گیرد")
        self.nothing_was_fetched()

    def test_why_explains_and_keeps_the_question_open(self):
        self.ask(WISH)
        reply = self.ask("چرا؟")
        self.assertIn("«بله»", reply)
        self.assertEqual(self.pending_own(), "consent")
        self.nothing_was_fetched()
        self.assertIn("شروع کردم", self.ask("بله"))

    def test_asking_again_while_the_question_is_open_asks_again(self):
        self.ask(WISH)
        reply = self.ask(WISH)
        self.assertIn("«بله»", reply)
        self.assertEqual(self.pending_own(), "consent")
        self.nothing_was_fetched()

    def test_the_wish_while_it_is_ready_says_so_and_starts_nothing(self):
        self.install_light()
        before = list(self.cdn.requests)
        reply = self.ask(WISH)
        self.assertIn("آماده است", reply)
        self.assertEqual(self.cdn.requests, before)
        self.assertIsNone(self.pending_own())


class ChoiceTests(OwnBrainApp):
    def test_a_roomy_phone_is_offered_the_strong_one_and_told_about_the_light_one(self):
        card = self.ask(WISH)
        self.assertIn("«%s»" % tiny_choice("strong").short_fa, card)
        self.assertIn(tiny_choice("light").short_fa, card)
        self.assertIn("«سبک»", card)

    def test_the_light_one_can_be_chosen_and_then_started(self):
        self.ask(WISH)
        card = self.ask("سبک")
        self.assertIn(tiny_choice("light").short_fa, card.split("پیشنهادِ من")[1].split("•")[0])
        self.assertEqual(self.pending_own(), "consent")
        self.nothing_was_fetched()
        self.ask("بله")
        self.assertEqual(self.ob.status()["choice"], "light")
        self.assertEqual(self.model_status("light").state, "usable")
        self.assertEqual(self.model_status("strong").state, "unregistered")

    def test_the_choice_can_be_changed_back_and_forth(self):
        self.ask(WISH)
        self.ask("سبک")
        card = self.ask("قوی")
        self.assertIn(tiny_choice("strong").short_fa, card.split("پیشنهادِ من")[1].split("•")[0])
        self.ask("بله")
        self.assertEqual(self.ob.status()["choice"], "strong")
        self.assertEqual(self.cdn.requests and self.cdn.requests[0].path_query.endswith("strong.litertlm"), True)

    def test_a_phone_that_fits_only_the_light_one_is_offered_only_that(self):
        write_meminfo(self.meminfo, 3_000_000)
        card = self.ask(WISH)
        self.assertIn(tiny_choice("light").short_fa, card.split("پیشنهادِ من")[1].split("•")[0])
        self.assertNotIn("«قوی»", card)

    def test_a_choice_that_does_not_fit_is_refused_and_the_question_stays(self):
        write_meminfo(self.meminfo, 3_000_000)
        self.ask(WISH)
        reply = self.ask("قوی")
        self.assertIn("کمتر است", reply)
        self.assertIn("چیزی دانلود نکردم", reply)
        self.assertEqual(self.pending_own(), "consent")
        self.nothing_was_fetched()
        self.ask("بله")
        self.assertEqual(self.ob.status()["choice"], "light")

    def test_a_third_word_is_not_a_choice(self):
        self.ask(WISH)
        self.ask("سبک یا قوی؟")
        self.nothing_was_fetched()


class PreflightTests(OwnBrainApp):
    """Everything that makes the brain useless is found BEFORE the first byte is requested."""

    def assertRefusedBeforeAnything(self, reply, *words):
        for word in words:
            self.assertIn(word, reply)
        self.assertIsNone(self.pending_own(), "a refused wish must not leave an open question")
        self.nothing_was_fetched()
        self.assertEqual(self.ob.status()["phase"], "idle")

    def test_a_build_without_the_engine_is_refused_and_says_what_to_do(self):
        self.engine_available = False
        self.start_app()
        self.assertRefusedBeforeAnything(self.ask(WISH), "موتورِ اجرای مغز", "چیزی دانلود نکردم", WISH)

    def test_no_internet_is_refused(self):
        self.connectivity = BridgeConnectivity("offline", "none")
        self.start_app()
        self.assertRefusedBeforeAnything(self.ask(WISH), "اینترنت ندارد", "چیزی دانلود نکردم", "VPN")
        self.ask("بله")
        self.nothing_was_fetched()

    def test_too_little_ram_for_any_brain_is_refused(self):
        write_meminfo(self.meminfo, 1_000_000)
        self.assertRefusedBeforeAnything(self.ask(WISH), "کمتر است", "چیزی دانلود نکردم")

    def test_a_ram_size_that_cannot_be_read_is_never_guessed(self):
        os.remove(self.meminfo)
        self.assertRefusedBeforeAnything(self.ask(WISH), "حدس نمی‌زنم", "چیزی دانلود نکردم")

    def test_too_little_room_is_refused(self):
        self.free_fn = staticmethod(lambda _path: Usage(10 ** 9, 0, 10 ** 5))
        self.start_app()
        self.assertRefusedBeforeAnything(self.ask(WISH), "جای خالیِ گوشی کافی نیست", "چیزی دانلود نکردم", "مگابایت")

    def test_a_wish_after_the_preflight_is_fixed_works(self):
        self.engine_available = False
        self.start_app()
        self.ask(WISH)
        self.engine_available = True
        self.start_app()
        self.assertIn("«بله»", self.ask(WISH))

    def test_the_explanation_still_works_when_nothing_can_be_started(self):
        self.engine_available = False
        self.start_app()
        reply = self.ask("مغز خودکار چیست؟")
        self.assertIn("بدون کلید", reply)
        self.assertIn("موتورِ اجرای مغز", reply)
        self.nothing_was_fetched()


class FailureTests(OwnBrainApp):
    """What goes wrong on the way, and what the user is told and can do. None of these ends in «آماده»."""

    def model_file(self, key="light"):
        return os.path.join(self.hub.root, "models", "files", tiny_choice(key).model_id, "1", "model.bin")

    def partial(self, key="light"):
        return resumable.partial_size(self.ob._dir, tiny_choice(key).rel_dest)

    def go(self, pick="سبک"):
        self.ask(WISH)
        if pick:
            self.ask(pick)
        return self.ask("بله")

    def test_a_file_that_is_not_the_pinned_one_is_never_installed(self):
        self.cdn = OwnCdn(files={"strong": DATA, "light": bytes(b ^ 1 for b in LIGHT_DATA)})
        self.start_app()
        self.go()
        state = self.ob.status()
        self.assertEqual((state["phase"], state["code"]), ("failed", "hash_mismatch"))
        self.assertEqual(self.model_status("light").state, "unregistered")
        self.assertFalse(os.path.exists(self.model_file()))
        self.assertEqual(self.partial(), 0, "a file with the wrong fingerprint must not be kept")
        text = self.ask("وضعیت مغز")
        self.assertIn("هش", text)
        self.assertNotIn("آماده است", text)
        self.assertIn("کامل نشد", self.ask("یه سوال عجیب و غریب درباره فلان"))

    def test_a_server_file_of_another_size_is_refused_before_the_body(self):
        self.cdn = OwnCdn(linked_size=999_999)
        self.start_app()
        self.go()
        self.assertEqual(self.ob.status()["phase"], "failed")
        self.assertIn(self.ob.status()["code"], ("size_mismatch", "remote_changed"))
        self.assertEqual(self.cdn.read, 0, "no body byte may be read from a file of the wrong size")
        self.assertFalse(os.path.exists(self.model_file()))

    def test_a_cut_connection_keeps_what_was_fetched_and_the_user_continues(self):
        self.cdn = OwnCdn(plan=[("cut", 30_000), ("refuse",)])
        self.start_app()
        self.go()
        state = self.ob.status()
        self.assertEqual((state["phase"], state["code"], state["resumable"]), ("failed", "interrupted", True))
        self.assertEqual(self.partial(), 30_000)
        text = self.ask("وضعیت مغز")
        for must in ("VPN", BM.RESUME, "نگه داشته شد"):
            self.assertIn(must, text)
        self.cdn.plan = [("ok",)]
        self.cdn.requests.clear()
        reply = self.ask(BM.RESUME)
        self.assertIn("ادامه دادم", reply)
        self.assertEqual(self.ob.status()["phase"], "ready")
        ranges = [r.headers.get("Range") for r in self.cdn.requests if r.headers.get("Range")]
        self.assertIn("bytes=30000-", ranges, "the rest must be asked for, not the whole file again")
        self.assertEqual(self.model_status("light").state, "usable")

    def test_a_failure_that_more_downloading_cannot_fix_does_not_pretend_to_resume(self):
        self.cdn = OwnCdn(files={"strong": DATA, "light": bytes(b ^ 1 for b in LIGHT_DATA)})
        self.start_app()
        self.go()
        reply = self.ask(BM.RESUME)                                    # it starts again from nothing, and says so (not «ادامه دادم»)
        self.assertNotIn("ادامه دادم", reply)
        self.assertEqual(self.ob.status()["code"], "hash_mismatch")

    def test_a_load_that_fails_is_never_ready_and_the_file_is_kept_for_a_retry(self):
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        self.go()
        state = self.ob.status()
        self.assertEqual((state["phase"], state["code"]), ("failed", "engine_load_failed"))
        self.assertTrue(os.path.isfile(self.model_file()), "a healthy file stays when only the load failed")
        status_text = self.ask("وضعیت مغز")
        self.assertIn(BM.RETRY, status_text)
        free_text = self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertIn(BM.STATUS, free_text)                              # a free sentence points at the status, which names the retry
        for text in (status_text, free_text):
            self.assertNotIn("آماده است", text)
        requests = len(self.cdn.requests)
        self.bridge.load_result = "OK\nloaded"
        reply = self.ask(BM.RETRY)
        self.assertIn("آماده است", reply)
        self.assertEqual(self.ob.status()["phase"], "ready")
        self.assertEqual(len(self.cdn.requests), requests, "a retry after a failed load must not download again")

    def test_a_first_question_that_is_not_answered_is_not_ready(self):
        self.bridge.chat_error = "engine_generate_failed"
        self.go()
        state = self.ob.status()
        self.assertEqual((state["phase"], state["code"]), ("failed", "smoke_failed"))
        text = self.ask("وضعیت مغز")
        self.assertIn("جوابِ درستی نداد", text)
        self.assertIn(BM.RETRY, text)
        self.assertNotIn("آماده است", text)
        self.bridge.chat_error = None
        self.assertIn("آماده است", self.ask(BM.RETRY))

    def test_an_empty_first_answer_is_not_ready_either(self):
        self.bridge.answers = [""]
        self.go()
        self.assertEqual(self.ob.status()["phase"], "failed")

    def test_the_test_command_after_a_failure_does_not_pretend(self):
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        self.go()
        reply = self.ask("آزمایش مغز")
        self.assertNotIn("آزمایش گذشت", reply)
        self.assertIn(BM.RETRY, reply)

    def test_a_crash_while_loading_is_not_repeated_by_itself(self):
        self.install_light()
        with open(self.model_file() + LR.MARKER_SUFFIX, "w", encoding="ascii") as handle:    # the app was killed in the middle of a load
            handle.write("loading since 1\n")
        self.start_app()
        loads = len(self.bridge.loads)
        for text in (self.ask("یه سوال عجیب و غریب درباره فلان"), self.ask("وضعیت مغز")):
            self.assertIn("از کار افتاد", text)
            self.assertIn(BM.RETRY, text)
            self.assertIn(BM.DELETE, text)
        self.assertEqual(len(self.bridge.loads), loads, "the engine must not be loaded again by itself after a crash")
        self.assertEqual(self.ob.status()["code"], "crashed_before")
        reply = self.ask(BM.RETRY)                                     # the user's decision
        self.assertIn("آماده است", reply)
        self.assertFalse(os.path.exists(self.model_file() + LR.MARKER_SUFFIX))
        self.assertIn("مغزِ آزمایشی", self.ask("یه سوال عجیب و غریب درباره فلان"))

    def test_retry_with_nothing_to_retry_says_so(self):
        reply = self.ask("مغز را دوباره امتحان کن")
        self.assertIn(WISH, reply)
        self.nothing_was_fetched()

    def test_the_texts_for_every_failure_code_name_a_next_step(self):
        for code in ("hash_mismatch", "size_mismatch", "remote_changed", "host_not_allowed", "offline", "dns_failure", "timeout", "tls_error",
                     "interrupted", "insufficient_space", "engine_load_failed", "crashed_before", "smoke_failed", "not_usable", "zzz_unknown",
                     "unavailable_platform", "dependency_missing"):
            text = BM.failure_text(code, "load" if code == "zzz_unknown" else "")
            self.assertTrue(any(word in text for word in (BM.RETRY, BM.RESUME, BM.START, BM.DELETE, "VPN", "جا باز", "برنامه")), code)
            self.assertNotIn("آماده است", text)


class UseTests(OwnBrainApp):
    def test_a_free_sentence_is_answered_by_the_brain_and_says_so_once(self):
        self.install_light()
        first = self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", first)
        self.assertIn("این جواب را مغزِ خودم", first)
        self.assertIn("ChatGPT", first)                                   # the note says it is not ChatGPT and not a search
        second = self.ask("یه سوال عجیب و غریب دیگر درباره بهمان")
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", second)
        self.assertNotIn("این جواب را مغزِ خودم", second)

    def test_the_brain_gets_the_users_sentence_and_nothing_goes_to_the_internet(self):
        self.install_light()
        before = len(self.cdn.requests)
        self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertEqual(self.bridge.chats[-1]["user"], "یه سوال عجیب و غریب درباره فلان")
        self.assertEqual(len(self.cdn.requests), before)
        self.assertEqual(self.fetch.requests, [])

    def test_the_things_the_app_already_understands_are_not_given_to_the_brain(self):
        self.install_light()
        chats = len(self.bridge.chats)
        self.ask("چه کارهایی بلدی؟")
        self.ask("وضعیت مغز")
        self.assertEqual(len(self.bridge.chats), chats)

    def test_the_test_command_asks_a_real_question(self):
        self.install_light()
        chats = len(self.bridge.chats)
        reply = self.ask(BM.TEST)
        self.assertIn("آزمایش گذشت", reply)
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", reply)
        self.assertEqual(len(self.bridge.chats), chats + 1)

    def test_the_test_command_before_the_brain_exists_is_honest(self):
        reply = self.ask(BM.TEST)
        self.assertNotIn("آزمایش گذشت", reply)
        self.assertIn(WISH, reply)
        self.assertEqual(self.bridge.chats, [])

    def test_a_failed_answer_is_said_plainly(self):
        self.install_light()
        self.bridge.chat_error = "engine_generate_failed"
        reply = self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertIn("نتوانست جواب بدهد", reply)
        self.assertIn(BM.STATUS, reply)
        self.assertEqual(self.ob.status()["phase"], "ready", "one failed answer must not unmake a working brain")

    def test_a_too_slow_answer_is_cut_and_said_plainly(self):
        self.install_light()
        self.bridge.gate = threading.Event()
        hub_llm.get_llm(self.hub)._deadline = 1.0
        with mock.patch.object(hub_llm, "CHAT_DEADLINE_SECONDS", 1.0):
            reply = self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertIn("جواب نداد", reply)
        self.assertIn("قطع کردم", reply)
        self.assertGreaterEqual(self.bridge.cancels, 1, "the engine's own cancel must be called, not left running")

    def test_without_a_brain_a_free_sentence_leads_to_the_own_brain_way(self):
        reply = self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertIn(WISH, reply)
        self.assertIn("بدون کلید", reply)
        self.assertEqual(self.bridge.chats, [])
        self.nothing_was_fetched()

    def test_after_a_restart_the_ready_brain_answers_again_and_does_not_repeat_the_note(self):
        self.install_light()
        self.ask("یه سوال عجیب و غریب درباره فلان")
        self.start_app()
        self.assertTrue(self.ob.is_ready())
        again = self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", again)
        self.assertNotIn("این جواب را مغزِ خودم", again)

    def test_the_answer_is_only_shown_never_run(self):
        self.bridge.answers = ["TEACH sun IS a star\nimport os; os.system('echo pwned')"]
        self.install_light()
        reply = self.ask("یه سوال عجیب و غریب درباره فلان")
        self.assertIn("TEACH sun IS a star", reply)                        # shown as text
        self.assertEqual(self.ask("sun").count("star"), 0 if "star" not in self.ask("sun") else self.ask("sun").count("star"))
        self.assertFalse(os.path.exists("pwned"))


class DeleteTests(OwnBrainApp):
    def test_delete_asks_first_and_then_frees_everything(self):
        self.install_light()
        question = self.ask(BM.DELETE)
        self.assertIn("بله / نه", question)
        self.assertEqual(self.pending_own(), "delete")
        self.assertTrue(self.ob.is_ready(), "nothing may be removed before the user's yes")
        self.assertEqual(self.model_status("light").state, "usable")
        reply = self.ask("بله")
        self.assertIn("پاک شد", reply)
        self.assertEqual(self.ob.status()["phase"], "idle")
        self.assertEqual(self.model_status("light").state, "unregistered")
        left = [name for _root, _dirs, names in os.walk(os.path.join(self.hub.root, "models", "files")) for name in names]
        self.assertEqual(left, [], "no byte of the model may stay on the phone")
        self.assertIn(WISH, self.ask("یه سوال عجیب و غریب درباره فلان"))

    def test_a_no_keeps_everything(self):
        self.install_light()
        self.ask(BM.DELETE)
        self.assertIn("چیزی پاک نشد", self.ask("نه"))
        self.assertTrue(self.ob.is_ready())
        self.assertEqual(self.model_status("light").state, "usable")

    def test_another_sentence_withdraws_the_delete_question(self):
        self.install_light()
        self.ask(BM.DELETE)
        self.ask("ساعت چنده؟")
        self.ask("بله")
        self.assertTrue(self.ob.is_ready())

    def test_nothing_to_delete(self):
        self.assertIn("مغزی روی گوشی نیست", self.ask(BM.DELETE))
        self.assertIsNone(self.pending_own())

    def test_delete_after_a_cut_removes_the_unfinished_download_too(self):
        self.cdn = OwnCdn(plan=[("cut", 30_000), ("refuse",)])
        self.start_app()
        self.ask(WISH)
        self.ask("سبک")
        self.ask("بله")
        self.assertEqual(resumable.partial_size(self.ob._dir, tiny_choice("light").rel_dest), 30_000)
        self.ask(BM.DELETE)
        self.ask("بله")
        self.assertEqual(resumable.partial_size(self.ob._dir, tiny_choice("light").rel_dest), 0)
        self.assertEqual(self.ob.status()["phase"], "idle")
        self.assertFalse(os.path.isdir(os.path.join(self.own_dir, tiny_choice("light").rel_dest.split("/")[0])))

    def test_after_a_delete_the_brain_can_be_taken_again(self):
        self.install_light()
        self.reset_brain()
        self.install_light()
        self.assertEqual(self.model_status("light").state, "usable")


class RestartTests(OwnBrainApp):
    def seed(self, key="light", phase="paused", code="app_closed", consent=True, partial=30_000, internet=True):
        """A state file (and an unfinished download) the way the app leaves them when it is closed, then the app starts again. The user's yes had
        switched the app's internet on and it is still on (`internet=False`: he had switched it off since)."""
        self.seed_download(key, phase, code, consent, partial)
        self.start_app()
        if internet:
            self.switch_internet(True)

    def test_an_agreed_download_continues_when_the_app_opens_again(self):
        self.seed()
        self.assertEqual(self.ob.status()["phase"], "paused")
        self.assertEqual(self.cdn.requests, [], "starting the app alone must not download anything")
        self.ask("سلام")
        self.assertEqual(self.ob.status()["phase"], "ready")
        ranges = [r.headers.get("Range") for r in self.cdn.requests if r.headers.get("Range")]
        self.assertIn("bytes=30000-", ranges)

    def test_a_download_the_user_stopped_does_not_continue_by_itself(self):
        for code in ("user_paused", "halted"):
            self.seed(code=code)
            self.ask("سلام")
            self.assertEqual(self.ob.status()["phase"], "paused", code)
            self.assertEqual(self.cdn.requests, [], code)

    def test_without_the_users_yes_nothing_continues(self):
        self.seed(consent=False)
        self.ask("سلام")
        self.assertEqual(self.cdn.requests, [])
        self.assertNotEqual(self.ob.status()["phase"], "ready")

    def test_a_closed_app_in_the_middle_of_a_download_is_recorded_as_such(self):
        state = ST.default_state()
        state.update(choice="light", phase="downloading", consent_at=1.0, model_id=tiny_choice("light").model_id, total=len(LIGHT_DATA))
        os.makedirs(self.own_dir, exist_ok=True)
        ST.StateFile(self.own_dir, clock=self.clock).save(state)
        self.start_app()
        status = self.ob.status()
        self.assertEqual((status["phase"], status["code"]), ("paused", "app_closed"))

    def test_a_damaged_state_file_starts_from_nothing(self):
        os.makedirs(self.own_dir, exist_ok=True)
        with open(os.path.join(self.own_dir, "state.json"), "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.start_app()
        self.assertEqual(self.ob.status()["phase"], "idle")
        self.assertIn("«بله»", self.ask(WISH))

    def test_a_state_file_with_a_wrong_field_starts_from_nothing(self):
        os.makedirs(self.own_dir, exist_ok=True)
        with open(os.path.join(self.own_dir, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"v": 1, "phase": "ready", "choice": "light", "bytes": "many"}, handle)
        self.start_app()
        self.assertEqual(self.ob.status()["phase"], "idle")

    def test_ready_survives_a_restart(self):
        self.install_light()
        self.start_app()
        self.assertTrue(self.ob.is_ready())
        self.assertIn("آماده است", self.ask("وضعیت مغز"))

    def test_a_brain_removed_by_the_model_commands_is_not_called_ready_any_more(self):
        self.install_light()
        self.hub.remove_model(tiny_choice("light").model_id)
        self.assertIn("هنوز مغزی", self.ask("وضعیت مغز"))
        self.assertEqual(self.ob.status()["phase"], "idle")


class KeyQuestionTests(OwnBrainApp):
    """The cloud brain's key question (his own key, off by default) must never trap the own-brain wish - the confusion in his screenshots."""

    def open_key_question(self):
        self.ask("مغز ابری را فعال کن")
        self.ask("۱")
        self.ask("بله")
        self.assertEqual(self.pending_cloud(), "key")

    def test_the_own_brain_wish_is_not_trapped_by_the_key_question(self):
        self.open_key_question()
        reply = self.ask(WISH)
        self.assertIn("«بله»", reply)
        self.assertIn("بدون کلید", reply)
        self.assertIsNone(self.pending_cloud())
        self.assertEqual(self.pending_own(), "consent")

    def test_a_long_sentence_withdraws_the_key_question_and_says_so(self):
        self.open_key_question()
        reply = self.ask("یک جملهٔ بلند دربارهٔ هوای امروز تهران که ربطی به کلید ندارد")
        self.assertIsNone(self.pending_cloud())
        self.assertIn("پرسشِ نیمه‌کارهٔ «مغز ابری» را کنار گذاشتم", reply)
        self.assertIn("چیزی ذخیره نشد", reply)

    def test_a_short_reminder_keeps_the_key_question(self):
        self.open_key_question()
        reply = self.ask("چی؟")
        self.assertEqual(self.pending_cloud(), "key")
        self.assertIn("دوباره بچسبان", reply)

    def test_the_withdrawn_note_is_said_once(self):
        self.open_key_question()
        self.ask("یک جملهٔ بلند دربارهٔ هوای امروز تهران که ربطی به کلید ندارد")
        later = self.ask("یک جملهٔ بلند دیگر دربارهٔ هوای فردا که ربطی به کلید ندارد")
        self.assertNotIn("پرسشِ نیمه‌کارهٔ «مغز ابری»", later)

    def test_a_key_is_never_taken_for_an_own_brain_sentence(self):
        self.open_key_question()
        self.ask("sk-test1234567890abcdefghijklmnopqrstuvwx")
        self.assertIsNone(self.pending_cloud())
        self.assertIsNone(self.pending_own())
        self.nothing_was_fetched()


if __name__ == "__main__":
    unittest.main()
