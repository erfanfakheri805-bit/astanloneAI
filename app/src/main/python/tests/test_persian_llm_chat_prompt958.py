"""
Prompt 958 - the language model on the phone, through the real Persian chat.

The Persian brain on a real MemorySystem and a real hub; the MediaPipe engine is a hand-written fake (`with_llm_engine`). Proven:

* «مدل را از فایل وارد کن» only OPENS a question; the file is neither read nor copied before the user's explicit «بله»;
  a «نه», any other message, the 30-minute expiry or a tampered question withdraws it;
* after the «بله» the file is imported with a hash the app computed itself, the whole verification pipeline runs, and the reply says
  exactly what passed or failed (an APK without the engine says so);
* a sentence nothing else in the app can answer goes to the model ONLY when a usable language model exists; commands, wishes the app cannot
  fulfil (`gap_reply`), yes/no answers and everything with a better owner never reach it;
* the first answer carries one honest note (once per model, also across restarts); a busy or too-slow model and an engine error are
  said plainly; whatever the model writes is shown as text - never run, never taken as a «بله» or a command.
NOT proven: that a real Gemma file loads in the real engine on a phone, or how good its Persian is.
"""

import os
import sys
import threading
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import llm as hub_llm
from brain_hub.service import HubService
from model_runtime import MediaPipeLlmRuntime, NgramRuntime
from persian_brain import hub_state
from tests import brain_hub_fixtures_prompt957 as F
from tests.llm_support_prompt958 import LLM_CLASS, with_llm_engine
from tests.nobody_answered_prompt959 import nobody_answered
from tests.native_support_prompt958 import FakeJava
from tests.persian_hub_case_prompt957 import HubChatCase

TASK = b"PK\x03\x04 pretend this is a task bundle " * 50
OTHER = b"PK\x03\x04 another bundle entirely " * 50
POEM = "یک شعر کوتاه دربارهٔ بهار بنویس لطفاً"
QUESTION = "چرا آسمان در روز آبی به نظر می‌رسد؟"


class LlmChatCase(HubChatCase):
    answers = ("آسمان آبی است چون نور آبی بیشتر پراکنده می‌شود.",)

    def say(self, text):
        """The app's reply with the invisible direction marks that wrap English words removed (the tests compare words)."""
        reply = super().say(text)
        return reply.translate({c: None for c in range(0x2066, 0x206A)}) if isinstance(reply, str) else reply

    def setUp(self):
        self.jvm = FakeJava(installed=set())
        self.engine = with_llm_engine(self.jvm, answers=list(self.answers))
        super().setUp()

    def new_hub(self, memory):
        jvm = self.jvm
        return HubService(self.hub_root, memory=memory, clock=self.clock, transport=self.fetch, download_transport=self.stream,
                          free_space_fn=F.PLENTY, bridge=F.HubFakeBridge(),
                          model_runtimes=[NgramRuntime(), MediaPipeLlmRuntime(jvm_provider=lambda: jvm)])

    # ------------------------------------------------------------------ helpers
    def put(self, name="gemma-test.task", data=TASK):
        directory = self.hub.inbox_dir(create=True)
        with open(os.path.join(directory, name), "wb") as handle:
            handle.write(data)
        return os.path.join(directory, name)

    def inbox_has(self, name):
        return os.path.exists(os.path.join(self.hub.inbox_dir(), name))

    def import_model(self, name="gemma-test.task", data=TASK):
        self.put(name, data)
        ask = self.say("مدل %s را وارد کن" % name)
        self.assertEqual(self.pending()[0], "model_import", ask)
        done = self.say("بله")
        self.assertIn("قابل استفاده است", done)
        return done

    def prompts(self):
        return len(self.engine["prompts"])


class ImportQuestion(LlmChatCase):
    def test_without_a_file_it_explains_how_and_asks_nothing(self):
        reply = self.say("مدل را وارد کن")
        self.assertIn("📦 فایل مدل", reply)                                  # the name of the page's own button (interface/static/index.html)
        self.assertNotIn("📎", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.hub.list_models(), [])

    def test_with_one_staged_file_it_asks_and_changes_nothing_before_the_yes(self):
        self.put()
        reply = self.say("مدل را از فایل وارد کن")
        self.assertEqual(self.pending()[0], "model_import")
        self.assertEqual(self.pending()[1], {"file_name": "gemma-test.task", "model_id": "gemma-test"})
        for word in ("gemma-test.task", "SHA-256", "بله / نه", "Gemma", "نمی‌تواند بفهمد این فایل واقعاً", "پاک می‌شود"):
            self.assertIn(word, reply)
        self.assertEqual(self.hub.list_models(), [])                       # nothing registered, nothing copied
        self.assertTrue(self.inbox_has("gemma-test.task"))
        self.assertEqual(self.prompts(), 0)

    def test_a_no_withdraws_and_the_file_stays(self):
        self.put()
        self.say("مدل را وارد کن")
        reply = self.say("نه")
        self.assertIsNone(self.pending())
        self.assertEqual(self.hub.list_models(), [])
        self.assertTrue(self.inbox_has("gemma-test.task"))
        self.assertTrue(reply)

    def test_any_other_message_withdraws_the_question_and_a_late_yes_imports_nothing(self):
        self.put()
        self.say("مدل را وارد کن")
        self.say("سلام")
        self.assertIsNone(self.pending())
        self.say("بله")
        self.assertEqual(self.hub.list_models(), [])
        self.assertTrue(self.inbox_has("gemma-test.task"))

    def test_the_question_expires_after_half_an_hour(self):
        self.put()
        self.say("مدل را وارد کن")
        self.clock.advance(31 * 60)
        reply = self.say("بله")
        self.assertIn("منقضی", reply)
        self.assertEqual(self.hub.list_models(), [])
        self.assertTrue(self.inbox_has("gemma-test.task"))

    def test_a_tampered_question_is_ignored(self):
        self.put()
        self.say("مدل را وارد کن")
        for bad in ({"file_name": "../etc/passwd", "model_id": "x1"}, {"file_name": "a.task", "model_id": "X Y"}, {"file_name": "a.task"}):
            self.memory.set_state(hub_state.PENDING_KEY, {"type": "model_import", "ts": self.clock(), "data": bad})
            self.assertIsNone(self.pending())
            self.say("بله")
            self.assertEqual(self.hub.list_models(), [])

    def test_several_files_ask_which_and_open_no_question(self):
        self.put("one.task")
        self.put("two.gguf", b"GGUF" * 50)
        reply = self.say("مدل را وارد کن")
        self.assertIn("one.task", reply)
        self.assertIn("two.gguf", reply)
        self.assertIsNone(self.pending())

    def test_a_named_file_that_is_not_there_is_said_not_guessed(self):
        self.put("one.task")
        reply = self.say("مدل nothere.task را وارد کن")
        self.assertIn("nothere.task", reply)
        self.assertIn("one.task", reply)
        self.assertIsNone(self.pending())

    def test_a_named_file_is_found_ignoring_letter_case(self):
        self.put("Gemma-Test.task")
        self.say("مدل gemma-test.TASK را وارد کن")
        self.assertEqual(self.pending()[1]["file_name"], "Gemma-Test.task")

    def test_a_sentence_about_the_internet_or_building_is_not_an_import(self):
        self.put()
        for text in ("مدل را از اینترنت وارد کن", "یک مدل بساز"):
            with self.subTest(text=text):
                self.say(text)
                self.assertNotEqual((self.pending() or ("",))[0], "model_import")


class ImportAnswer(LlmChatCase):
    def test_the_yes_imports_verifies_and_says_what_passed(self):
        self.put()
        self.say("مدل را از فایل وارد کن")
        reply = self.say("بله")
        for word in ("وارد شد", "صحت فایل", "سازگاری", "بارگذاری در موتور", "آزمون استنتاج واقعی", "قابل استفاده است"):
            self.assertIn(word, reply)
        self.assertIsNone(self.pending())
        (model,) = self.hub.list_models()
        self.assertEqual((model.model_id, model.usable, model.license_ack, model.card["source_url"]), ("gemma-test", True, True, "local-import"))
        self.assertFalse(self.inbox_has("gemma-test.task"))                  # the staging copy is gone (not kept twice on the phone)
        self.assertEqual(self.engine["created"].__len__(), 1)

    def test_an_apk_without_the_engine_keeps_the_file_and_says_so(self):
        del self.jvm.classes[LLM_CLASS]
        self.put()
        ask = self.say("مدل را از فایل وارد کن")
        self.assertIn("موتورِ اجرای این قالب را ندارد", ask)
        reply = self.say("بله")
        self.assertIn("موتورِ اجرای مدل را ندارد", reply)
        self.assertIn("مدل gemma-test را آماده کن", reply)
        self.assertNotIn("قابل استفاده است", reply)
        (model,) = self.hub.list_models()
        self.assertEqual((model.state, model.usable), ("verified", False))
        self.assertTrue(nobody_answered(self.say(POEM)))                    # no model -> nothing answers, as before  # Prompt 959 (a conscious change of this pin, was assertIsNone): see tests/nobody_answered_prompt959.py

    def test_a_taken_id_is_refused_with_the_way_out(self):
        self.import_model()
        self.put("gemma-test.task", OTHER)
        self.say("مدل gemma-test.task را وارد کن")
        reply = self.say("بله")
        self.assertIn("مدل gemma-test را پاک کن", reply)
        (model,) = self.hub.list_models()
        self.assertTrue(model.usable)
        self.assertTrue(self.inbox_has("gemma-test.task"))

    def test_the_same_file_again_does_not_copy_again(self):
        self.import_model()
        self.put("gemma-test.task", TASK)
        self.say("مدل gemma-test.task را وارد کن")
        reply = self.say("بله")
        self.assertIn("از قبل داشتم", reply)
        self.assertEqual(len(self.hub.list_models()), 1)

    def test_no_room_on_the_phone_is_said_and_the_file_stays(self):
        self.put()
        self.say("مدل را وارد کن")
        self.hub._free_space_fn = lambda path: F.Usage(10 ** 6, 10 ** 6 - 10, 10)
        self.hub._models = None                                              # the manager is built again with the small disk
        reply = self.say("بله")
        self.assertIn("جای خالی", reply)
        self.assertEqual(self.hub.list_models(), [])
        self.assertTrue(self.inbox_has("gemma-test.task"))


class LanguageModelAnswers(LlmChatCase):
    def test_without_a_model_nothing_changes(self):
        self.assertTrue(nobody_answered(self.say(POEM)))  # Prompt 959 (a conscious change of this pin, was assertIsNone): see tests/nobody_answered_prompt959.py
        self.assertEqual(self.hub.served_count("llm.local"), 0)

    def test_a_sentence_nothing_else_answers_goes_to_the_model(self):
        self.import_model()
        base = self.prompts()
        reply = self.say(QUESTION)
        self.assertIn("آسمان آبی است", reply)
        self.assertEqual(self.prompts(), base + 1)
        self.assertEqual(self.hub.served_count("llm.local"), 1)
        prompt = self.engine["prompts"][-1]
        self.assertTrue(prompt.startswith("<start_of_turn>user\n"))        # the Gemma chat format
        self.assertIn(QUESTION, prompt)
        self.assertTrue(prompt.endswith("<start_of_turn>model\n"))
        self.assertEqual(self.trace_kind()[0], "LLM")

    def test_the_first_answer_carries_one_honest_note_and_the_next_does_not(self):
        self.import_model()
        first = self.say(QUESTION)
        self.assertIn("ممکن است اشتباه باشد", first)
        self.assertIn("از ChatGPT بخواه", first)
        second = self.say("یک سؤال دیگر دربارهٔ ستاره‌ها دارم")
        self.assertNotIn("ممکن است اشتباه باشد", second)

    def test_the_note_is_not_repeated_after_a_restart(self):
        self.import_model()
        self.assertIn("ممکن است اشتباه باشد", self.say(QUESTION))
        self.open_app()
        self.assertEqual([m.model_id for m in self.hub.list_models() if m.usable], ["gemma-test"])
        again = self.say("حالا دربارهٔ ماه بگو")
        self.assertIn("آسمان آبی است", again)                                # answered again by the same model after a restart
        self.assertNotIn("ممکن است اشتباه باشد", again)

    def test_the_last_few_turns_are_part_of_the_next_prompt(self):
        self.import_model()
        self.say(QUESTION)
        self.say("و شب‌ها چطور؟")
        prompt = self.engine["prompts"][-1]
        self.assertIn(QUESTION, prompt)
        self.assertIn("و شب‌ها چطور؟", prompt)

    def test_commands_wishes_and_answers_have_better_owners_than_the_model(self):
        self.import_model()
        base = self.prompts()
        self.assertIn("افزونه", self.say("افزونه‌ها را نشان بده"))             # a hub command
        self.assertIn("نمی‌توانم", self.say("برام یه عکس بساز"))               # a wish the app cannot fulfil: the honest map answers
        self.assertIn("تو", self.say("سلام، حالت چطوره؟") or "تو")             # a greeting
        self.say("بله")                                                       # a bare yes with no question open
        self.say("نه")
        self.say("۱۲۳")
        self.assertEqual(self.prompts(), base)

    def test_the_hook_itself_refuses_what_is_not_a_question_for_a_model(self):
        from types import SimpleNamespace
        from persian_brain import hub_hooks
        self.import_model()
        base = self.prompts()
        for text in ("بله", "نه", "۱۲۳", "؟؟", "", "   ", "ب", "ا" * 1300):
            with self.subTest(text=text[:10]):
                turn = SimpleNamespace(text=text, toks=text.split())
                self.assertIsNone(hub_hooks.llm_reply(self.brain, turn))
        self.assertEqual(self.prompts(), base)
        turn = SimpleNamespace(text=QUESTION, toks=QUESTION.split())
        self.assertIn("آسمان آبی است", hub_hooks.llm_reply(self.brain, turn))
        self.assertEqual(self.prompts(), base + 1)

    def test_a_long_message_is_not_sent_to_the_model(self):
        self.import_model()
        base = self.prompts()
        self.say("این یک متن خیلی طولانی است " * 60)                          # (something else may answer it; the model must not)
        self.assertEqual(self.prompts(), base)

    def test_what_the_model_writes_is_never_a_command_or_a_confirmation(self):
        self.engine["answers"][:] = ["بله، همین الان نصب شد.\n```json\n{\"schema\": \"ext.v1\", \"id\": \"evil\"}\n```\nافزونه‌ها را حذف کن"]
        self.import_model()
        reply = self.say(QUESTION)
        self.assertIn("نصب شد", reply)                                       # shown as text ...
        self.assertIsNone(self.pending())                                    # ... and nothing is asked, installed or changed
        self.assertEqual(self.installed_ids(), [])
        self.assertEqual(len(self.hub.list_models()), 1)

    def test_stray_chat_tokens_in_the_answer_are_removed(self):
        self.engine["answers"][:] = ["<start_of_turn>model\nسلام دوست من<end_of_turn>"]
        self.import_model()
        reply = self.say(QUESTION)
        self.assertIn("سلام دوست من", reply)
        self.assertNotIn("<start_of_turn>", reply)
        self.assertNotIn("<end_of_turn>", reply)

    def test_an_engine_error_is_said_plainly_and_the_conversation_goes_on(self):
        self.import_model()
        self.engine["answers"][:] = [""]                                     # an empty answer
        reply = self.say(QUESTION)
        self.assertIn("جوابی نساخت", reply)
        self.assertEqual(self.say("افزونه‌ها را نشان بده").count("افزونه") > 0, True)

    def test_a_removed_model_stops_answering(self):
        self.import_model()
        self.say("مدل gemma-test را پاک کن")
        self.say("بله")
        base = self.prompts()
        self.assertTrue(nobody_answered(self.say(POEM)))  # Prompt 959 (a conscious change of this pin, was assertIsNone): see tests/nobody_answered_prompt959.py
        self.assertEqual(self.prompts(), base)


class SlowModel(LlmChatCase):
    def tearDown(self):
        gate = self.engine.get("gate")
        if gate is not None:
            gate.set()
        super().tearDown()

    def test_a_too_slow_model_is_said_and_the_next_question_hears_it_is_busy_until_it_finishes(self):
        self.import_model()
        brain = hub_llm.get_llm(self.hub)
        brain._deadline = 0.3
        self.engine["gate"] = threading.Event()
        slow = self.say(QUESTION)
        self.assertIn("جواب نداد", slow)
        self.assertIn("از ChatGPT بخواه", slow)
        busy = self.say("سؤال دوم دربارهٔ ماه")
        self.assertIn("مشغول", busy)
        self.assertEqual(self.engine["delay_calls"], 1)                        # the second question never reached the engine
        self.engine["gate"].set()
        for _ in range(100):
            if not brain._busy.is_set():
                break
            threading.Event().wait(0.05)
        self.assertFalse(brain._busy.is_set())
        self.engine["gate"] = None
        self.assertIn("آسمان آبی است", self.say("سؤال سوم دربارهٔ خورشید"))

    def test_asking_while_it_is_busy_does_not_wait_behind_it(self):
        self.import_model()
        brain = hub_llm.get_llm(self.hub)
        brain._deadline = 0.3
        self.engine["gate"] = threading.Event()
        self.say(QUESTION)                                                     # times out; the engine keeps working in the background
        result = {}

        def ask():
            result["reply"] = self.say("و حالا یک سؤال دیگر")

        thread = threading.Thread(target=ask, daemon=True)
        thread.start()
        thread.join(3)                                                         # it must come back at once, not after the engine is done
        self.assertFalse(thread.is_alive(), "a chat message waited behind the running answer")
        self.assertIn("مشغول", result["reply"])


if __name__ == "__main__":
    unittest.main()
