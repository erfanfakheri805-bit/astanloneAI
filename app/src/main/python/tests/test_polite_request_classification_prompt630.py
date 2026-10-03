"""Prompt 630 - leading politeness/greeting words must not hide the
request type ("Please explain X" is a command, "Hey, what is X" a
question). Backward compatible: everything else classifies as before."""
import os
import tempfile
import unittest

from understanding.engine import UnderstandingEngine
from understanding.nl_tokenizer import tokenize
from understanding.sentence_analysis import (
    detect_sentence_type, SENTENCE_COMMAND, SENTENCE_QUESTION,
    SENTENCE_STATEMENT, SENTENCE_UNKNOWN,
)
from understanding.language_detection import detect_language
from core.core import Core


def _type(text):
    return detect_sentence_type(text, tokenize(text), detect_language(text))


class TestPoliteRequestClassification(unittest.TestCase):
    def test_polite_commands(self):
        for t in ("Please explain recursion", "please tell me about Python",
                  "Kindly show me the list"):
            self.assertEqual(_type(t), SENTENCE_COMMAND, t)

    def test_polite_persian_commands(self):
        for t in ("لطفا توضیح بده", "لطفاً بگو پایتون چیست"):
            self.assertEqual(_type(t), SENTENCE_COMMAND, t)

    def test_greeting_comma_then_question_or_command(self):
        self.assertEqual(_type("Hey, what is Python"), SENTENCE_QUESTION)
        self.assertEqual(_type("Hello, explain recursion"), SENTENCE_COMMAND)

    def test_polite_question(self):
        self.assertEqual(_type("Please, what is Python"), SENTENCE_QUESTION)

    def test_unchanged_behavior(self):
        self.assertEqual(_type("Explain recursion."), SENTENCE_COMMAND)
        self.assertEqual(_type("What is Python"), SENTENCE_QUESTION)
        self.assertEqual(_type("Python is great"), SENTENCE_STATEMENT)
        self.assertEqual(_type("Hi is a greeting"), SENTENCE_STATEMENT)
        self.assertEqual(_type("Please is a word"), SENTENCE_STATEMENT)
        self.assertEqual(_type("Please"), SENTENCE_STATEMENT)
        self.assertEqual(_type(""), SENTENCE_UNKNOWN)
        self.assertEqual(_type("Please explain?"), SENTENCE_QUESTION)

    def test_politeness_word_not_an_entity(self):
        r = UnderstandingEngine().understand("Please explain recursion")
        self.assertEqual(r.sentence_type, SENTENCE_COMMAND)
        self.assertEqual([e["text"] for e in r.entities], ["recursion"])
        self.assertEqual(r.original_text, "Please explain recursion")


class TestPoliteRequestEndToEnd(unittest.TestCase):
    def test_intent_and_original_preserved_through_core(self):
        tmp = tempfile.mkdtemp()
        core = Core(memory_db_path=os.path.join(tmp, "c.db"),
                    skill_definitions_dir=os.path.join(tmp, "s"))
        core.process_input("Please explain recursion")
        u = core.get_last_language_understanding()
        held = u.normalized_input
        self.assertEqual(held, "Please explain recursion")
        self.assertEqual(u.original_input, "Please explain recursion")
        self.assertEqual(u.intent, "request_action")
        self.assertIs(core.get_last_response_normalized_input(), held)
        self.assertIs(core.get_last_response_plan(), u.response_plan)


if __name__ == "__main__":
    unittest.main()
