"""
Prompt 958 - `brain_hub.llm`: the layer between the Persian chat and a language model that `model_runtime` has made usable.

Proven: the prompt follows the chat format named by the model's file name (whole words only); an answer is cleaned of chat-format tokens,
control characters and bidirectional overrides and kept bounded; only real language models count (never the n-gram model, never a model
that is not usable); one answer at a time with a deadline; a busy or slow model never makes anything else wait; the last few turns are
remembered in memory only and forgotten when the model changes; nothing the model returns is interpreted.
"""

import os
import sys
import threading
import unittest
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import llm


def model(model_id="gemma-test", fmt="task", usable=True, title="مدل آزمایشی"):
    return SimpleNamespace(model_id=model_id, usable=usable, card={"format": fmt, "title": title})


class FakeHub:
    """Just the three things `LlmBrain` uses: `list_models`, `ask_model`, `note_served` (and `model_runtimes_info` for the status)."""

    def __init__(self, models=(), answers=("جواب",), engines=()):
        self.models, self.answers, self.engines = list(models), list(answers), list(engines)
        self.asked, self.served, self.gate, self.error, self.code = [], [], None, None, None
        self.list_calls = 0
        self.root = "/tmp/fake-hub"

    def list_models(self):
        self.list_calls += 1
        return list(self.models)

    def ask_model(self, model_id, prompt, *, max_tokens=64):
        self.asked.append((model_id, prompt, max_tokens))
        if self.gate is not None:
            self.gate.wait(10)
        if self.error is not None:
            raise self.error
        if self.code:
            return SimpleNamespace(ok=False, code=self.code, text="")
        text = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return SimpleNamespace(ok=True, code="ok", text=text)

    def note_served(self, node_id):
        self.served.append(node_id)

    def model_runtimes_info(self):
        return list(self.engines)


class PromptTemplates(unittest.TestCase):
    SYSTEM, TURNS, USER = "قواعد", [("سؤال یک", "جواب یک"), ("سؤال دو", "جواب دو")], "سؤال سه"

    def test_the_chat_format_comes_from_whole_words_of_the_name(self):
        names = {"gemma-3-1b-it": "gemma", "Gemma3": "gemma", "qwen2.5-0.5b": "chatml", "smollm2-360m": "chatml", "llama-3.2-1b": "llama3",
                 "phi-3-mini": "phi3", "phi3": "phi3", "dolphin3": "plain", "tinyllama": "plain", "deepseek-r1-distill": "plain",
                 "mystery": "plain", "": "plain"}
        for name, expected in names.items():
            with self.subTest(name=name):
                self.assertEqual(llm.family_of(name), expected)
        self.assertEqual(llm.family_of("model-1", "Gemma 3 کوچک"), "gemma")          # the title counts too

    def test_gemma_has_no_system_role_and_opens_the_first_user_turn_with_the_rules(self):
        text = llm.build_prompt("gemma", self.SYSTEM, self.TURNS, self.USER)
        self.assertTrue(text.startswith("<start_of_turn>user\nقواعد\n\nسؤال یک<end_of_turn>\n<start_of_turn>model\nجواب یک<end_of_turn>\n"))
        self.assertTrue(text.endswith("<start_of_turn>user\nسؤال سه<end_of_turn>\n<start_of_turn>model\n"))
        self.assertEqual(text.count("قواعد"), 1)
        self.assertNotIn("system", text)
        first = llm.build_prompt("gemma", self.SYSTEM, [], self.USER)
        self.assertEqual(first, "<start_of_turn>user\nقواعد\n\nسؤال سه<end_of_turn>\n<start_of_turn>model\n")

    def test_every_format_ends_where_the_model_must_start_writing(self):
        ends = {"chatml": "<|im_start|>assistant\n", "llama3": "<|start_header_id|>assistant<|end_header_id|>\n\n", "phi3": "<|assistant|>\n",
                "plain": "دستیار:"}
        for family, end in ends.items():
            with self.subTest(family=family):
                text = llm.build_prompt(family, self.SYSTEM, self.TURNS, self.USER)
                self.assertTrue(text.endswith(end), text[-60:])
                self.assertIn("سؤال سه", text)
                self.assertIn("جواب یک", text)
                self.assertIn("قواعد", text)

    def test_long_turns_and_questions_are_clipped(self):
        text = llm.build_prompt("plain", "s", [("ا" * 5000, "ب" * 5000)], "پ" * 5000)
        self.assertLess(len(text), llm.MAX_QUESTION_CHARS + 2 * llm.MAX_TURN_CHARS + 200)

    def test_the_system_text_tells_the_model_what_it_cannot_do(self):
        for word in ("فارسی", "نمی‌دانم", "هیچ کاری روی گوشی انجام نداده", "از ChatGPT بخواه"):
            self.assertIn(word, llm.SYSTEM_FA)


class CleanAnswer(unittest.TestCase):
    def test_chat_tokens_and_the_role_word_after_them_are_removed(self):
        self.assertEqual(llm.clean_answer("<start_of_turn>model\nسلام دوست من<end_of_turn>"), "سلام دوست من")
        self.assertEqual(llm.clean_answer("<|im_start|>assistant\nبله<|im_end|>"), "بله")
        self.assertEqual(llm.clean_answer("جواب<eos>"), "جواب")
        self.assertEqual(llm.clean_answer("model که یک کلمه است"), "model که یک کلمه است")           # an ordinary word stays

    def test_control_and_bidi_override_characters_are_removed_but_persian_marks_stay(self):
        dirty = "سلام\x00\x07 دوست\u202e من\u2066 خوب\u2069 است‌ بله\u200f"
        self.assertEqual(llm.clean_answer(dirty), "سلام دوست من خوب است‌ بله\u200f")

    def test_blank_runs_collapse_and_nothing_stays_empty_by_accident(self):
        self.assertEqual(llm.clean_answer("الف\n\n\n\n\nب"), "الف\n\nب")
        self.assertEqual(llm.clean_answer("   "), "")
        self.assertEqual(llm.clean_answer(None), "")
        self.assertEqual(llm.clean_answer("<end_of_turn>"), "")

    def test_a_long_answer_is_cut_at_a_sentence_end(self):
        sentence = "این یک جملهٔ نسبتاً بلند برای آزمایش است. "
        text = llm.clean_answer(sentence * 200)
        self.assertLessEqual(len(text), llm.MAX_ANSWER_CHARS + 2)
        self.assertTrue(text.endswith(".") or text.endswith("…"))

    def test_nothing_the_model_writes_is_interpreted(self):
        # a markup-looking answer is plain text for the chat; this function never evaluates or imports anything
        text = '```json\n{"schema": "ext.v1"}\n```\n__import__("os").system("x")'
        self.assertEqual(llm.clean_answer(text), text)


class WhichModel(unittest.TestCase):
    def test_only_usable_language_models_count(self):
        hub = FakeHub([model("n", "ngram-json"), model("g", "task", usable=False), model("ok", "task"), model("gg", "gguf")])
        brain = llm.LlmBrain(hub)
        self.assertEqual([m.model_id for m in brain.models()], ["ok", "gg"])
        self.assertEqual(brain.current().model_id, "gg")                         # the newest usable one
        self.assertEqual(llm.LlmBrain(FakeHub([model("n", "ngram-json")])).reply("سلام").code, "no_model")

    def test_the_model_that_answered_stays_the_current_one_while_it_is_usable(self):
        hub = FakeHub([model("first"), model("second")])
        brain = llm.LlmBrain(hub)
        self.assertEqual(brain.current().model_id, "second")
        brain._model_id = "first"
        self.assertEqual(brain.current().model_id, "first")
        hub.models = [model("second")]
        self.assertEqual(brain.current().model_id, "second")

    def test_a_hub_that_fails_is_just_no_model(self):
        hub = FakeHub()
        hub.list_models = lambda: (_ for _ in ()).throw(RuntimeError("disk"))
        self.assertIsNone(llm.LlmBrain(hub).current())

    def test_status_says_why_there_is_no_model(self):
        engine_off = {"name": "mediapipe_llm", "formats": ["task"], "available": False, "reason_fa": "موتور در این نسخه نیست"}
        self.assertEqual(llm.LlmBrain(FakeHub(engines=[engine_off])).status()["state"], "no_engine")
        self.assertEqual(llm.LlmBrain(FakeHub(engines=[engine_off])).status()["reason_fa"], "موتور در این نسخه نیست")
        engine_on = dict(engine_off, available=True)
        self.assertEqual(llm.LlmBrain(FakeHub(engines=[engine_on])).status()["state"], "no_model")
        ready = llm.LlmBrain(FakeHub([model("g")])).status()
        self.assertEqual((ready["state"], ready["model_id"], ready["title"]), ("ready", "g", "مدل آزمایشی"))


class OneAnswer(unittest.TestCase):
    def brain(self, **kw):
        hub = FakeHub([model("gemma-test")], **kw)
        return hub, llm.LlmBrain(hub, deadline_seconds=2)

    def test_a_good_answer_is_cleaned_counted_and_remembered(self):
        hub, brain = self.brain(answers=("<start_of_turn>model\nسلام!<end_of_turn>",))
        reply = brain.reply("  سلام  ")
        self.assertEqual((reply.ok, reply.text, reply.model_id), (True, "سلام!", "gemma-test"))
        self.assertEqual(hub.served, ["llm.local"])
        self.assertEqual(brain.used_count(), 1)
        model_id, prompt, max_tokens = hub.asked[0]
        self.assertEqual((model_id, max_tokens), ("gemma-test", llm.MAX_TOKENS))
        self.assertTrue(prompt.startswith("<start_of_turn>user\n"))
        brain.reply("دوباره")
        self.assertIn("سلام!", hub.asked[1][1])                                  # the first turn is in the second prompt

    def test_only_the_last_three_turns_are_kept_and_forget_clears_them(self):
        hub, brain = self.brain()
        for i in range(5):
            brain.reply("سؤال %d" % i)
        prompt = hub.asked[-1][1]                                               # question 4 (the fifth): turns 1, 2, 3 are remembered
        self.assertNotIn("سؤال 0", prompt)
        for i in (1, 2, 3, 4):
            self.assertIn("سؤال %d" % i, prompt)
        brain.forget()
        brain.reply("تازه")
        for i in range(5):
            self.assertNotIn("سؤال %d" % i, hub.asked[-1][1])

    def test_a_different_model_starts_with_a_clean_memory(self):
        hub, brain = self.brain()
        brain.reply("راز من این است")
        hub.models = [model("other-model")]
        brain.reply("بعدی")
        self.assertNotIn("راز من", hub.asked[-1][1])

    def test_bad_questions_never_reach_the_model(self):
        hub, brain = self.brain()
        for text in ("", "   ", None, "ا" * (llm.MAX_QUESTION_CHARS + 1)):
            with self.subTest(text=str(text)[:10]):
                self.assertEqual(brain.reply(text).code, "bad_question")
        self.assertEqual(hub.asked, [])
        self.assertEqual(hub.served, [])

    def test_a_refusal_or_an_exception_is_a_stable_code_and_is_not_counted(self):
        hub, brain = self.brain()
        hub.code = "model_not_usable"
        self.assertEqual(brain.reply("سلام").code, "model_not_usable")
        hub.code, hub.error = None, RuntimeError("secret detail that must not leak")
        failed = brain.reply("سلام")
        self.assertEqual((failed.ok, failed.code), (False, "RuntimeError"))
        self.assertNotIn("secret", repr(failed))
        self.assertEqual((hub.served, brain.used_count()), ([], 0))
        self.assertFalse(brain._busy.is_set())                                  # a failure never leaves it "busy"

    def test_an_answer_that_cleans_to_nothing_is_empty_not_ok(self):
        hub, brain = self.brain(answers=("<end_of_turn>",))
        self.assertEqual(brain.reply("سلام").code, "empty")
        self.assertEqual(hub.served, [])


class DeadlineAndBusy(unittest.TestCase):
    def test_a_slow_model_times_out_then_is_busy_until_it_ends_and_nobody_waits_behind_it(self):
        hub = FakeHub([model("gemma-test")])
        hub.gate = threading.Event()
        brain = llm.LlmBrain(hub, deadline_seconds=0.3)
        slow = brain.reply("سلام")
        self.assertEqual((slow.ok, slow.code), (False, "timeout"))
        self.assertGreaterEqual(slow.seconds, 0.3)
        calls = hub.list_calls
        self.assertEqual(brain.reply("باز هم").code, "busy")
        self.assertEqual(hub.list_calls, calls)                                # busy: the model manager was not even asked
        self.assertEqual(brain.current().model_id, "gemma-test")               # ... and the current model is known without asking it
        self.assertEqual(hub.list_calls, calls)
        self.assertEqual(brain.status()["state"], "busy")
        self.assertEqual(len(hub.asked), 1)
        hub.gate.set()
        for _ in range(100):
            if not brain._busy.is_set():
                break
            threading.Event().wait(0.05)
        self.assertFalse(brain._busy.is_set())
        hub.gate = None
        self.assertTrue(brain.reply("حالا").ok)
        self.assertEqual(brain.used_count(), 1)                                  # the timed-out answer was dropped, not counted

    def test_two_questions_at_once_make_one_answer_and_one_busy(self):
        hub = FakeHub([model("gemma-test")])
        hub.gate = threading.Event()
        brain = llm.LlmBrain(hub, deadline_seconds=5)
        results = []
        first = threading.Thread(target=lambda: results.append(brain.reply("اول")))
        first.start()
        for _ in range(100):
            if brain._busy.is_set():
                break
            threading.Event().wait(0.02)
        self.assertEqual(brain.reply("دوم").code, "busy")
        hub.gate.set()
        first.join(5)
        self.assertEqual([r.ok for r in results], [True])
        self.assertEqual(len(hub.asked), 1)


class OnePerHub(unittest.TestCase):
    def test_one_brain_per_hub_object(self):
        a, b = FakeHub([model("g")]), FakeHub([model("g")])
        self.assertIs(llm.get_llm(a), llm.get_llm(a))
        self.assertIsNot(llm.get_llm(a), llm.get_llm(b))
        self.assertIsNone(llm.get_llm(None))
        self.assertIsNone(llm.get_llm(object()))


if __name__ == "__main__":
    unittest.main()
