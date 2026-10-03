"""
Tests for the Understanding Engine foundation stage.

Run directly:
    python -m unittest tests.test_understanding_engine -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)

These tests check the STRUCTURED RESULT (language, sentence_type,
entities, relations, confidence, warnings) - not merely that nothing
crashes.
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from understanding.nl_tokenizer import tokenize, TOKEN_WORD, TOKEN_NUMBER, TOKEN_QUOTED, TOKEN_PUNCT
from understanding.language_detection import detect_language, LANGUAGE_ENGLISH, LANGUAGE_PERSIAN, LANGUAGE_UNKNOWN
from understanding.normalization import normalize
from understanding.sentence_analysis import (
    detect_sentence_type, SENTENCE_STATEMENT, SENTENCE_QUESTION, SENTENCE_COMMAND, SENTENCE_UNKNOWN,
)
from understanding.relation_extraction import extract_relation_candidates
from understanding.result import UnderstandingResult
from core.core import Core


def entity_texts(result):
    return [e["text"] for e in result.entities]


class TestNormalization(unittest.TestCase):
    def test_collapses_whitespace_and_keeps_original(self):
        r = normalize("  Python   is   a\t\tprogramming   language.  ")
        self.assertEqual(r.normalized_text, "Python is a programming language.")
        self.assertEqual(r.original_text, "  Python   is   a\t\tprogramming   language.  ")

    def test_none_input_is_empty_not_an_error(self):
        r = normalize(None)
        self.assertEqual(r.normalized_text, "")
        self.assertEqual(r.original_text, "")


class TestLanguageDetection(unittest.TestCase):
    def test_english(self):
        self.assertEqual(detect_language("Python is a programming language."), LANGUAGE_ENGLISH)

    def test_persian(self):
        self.assertEqual(detect_language("پایتون یک زبان برنامه‌نویسی است."), LANGUAGE_PERSIAN)

    def test_unknown_for_empty_or_symbols_only(self):
        self.assertEqual(detect_language(""), LANGUAGE_UNKNOWN)
        self.assertEqual(detect_language("123 !!! ???"), LANGUAGE_UNKNOWN)


class TestTokenizer(unittest.TestCase):
    def test_words_numbers_punct_and_quotes(self):
        tokens = tokenize('Python 3 uses "significant whitespace"!')
        kinds = [t.type for t in tokens]
        self.assertIn(TOKEN_WORD, kinds)
        self.assertIn(TOKEN_NUMBER, kinds)
        self.assertIn(TOKEN_QUOTED, kinds)
        self.assertIn(TOKEN_PUNCT, kinds)
        quoted = next(t for t in tokens if t.type == TOKEN_QUOTED)
        self.assertEqual(quoted.value, "significant whitespace")

    def test_empty_input_yields_no_tokens(self):
        self.assertEqual(tokenize(""), [])


class TestSentenceAnalysis(unittest.TestCase):
    def test_statement(self):
        tokens = tokenize("Python is a programming language.")
        self.assertEqual(
            detect_sentence_type("Python is a programming language.", tokens, LANGUAGE_ENGLISH),
            SENTENCE_STATEMENT,
        )

    def test_question_mark(self):
        tokens = tokenize("What is Python?")
        self.assertEqual(
            detect_sentence_type("What is Python?", tokens, LANGUAGE_ENGLISH), SENTENCE_QUESTION
        )

    def test_command_verb(self):
        tokens = tokenize("Teach me Python.")
        self.assertEqual(
            detect_sentence_type("Teach me Python.", tokens, LANGUAGE_ENGLISH), SENTENCE_COMMAND
        )

    def test_unknown_for_empty(self):
        self.assertEqual(detect_sentence_type("", [], LANGUAGE_UNKNOWN), SENTENCE_UNKNOWN)


class TestRelationExtraction(unittest.TestCase):
    def test_is_a(self):
        candidates = extract_relation_candidates("Python is a programming language.", SENTENCE_STATEMENT)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.subject, "Python")
        self.assertEqual(c.relation, "IS_A")
        self.assertEqual(c.object, "programming language")
        self.assertGreater(c.confidence, 0.0)

    def test_uses(self):
        candidates = extract_relation_candidates("Python uses indentation.", SENTENCE_STATEMENT)
        self.assertEqual(len(candidates), 1)
        self.assertEqual((candidates[0].subject, candidates[0].relation, candidates[0].object),
                          ("Python", "USES", "indentation"))

    def test_no_relations_for_non_statement(self):
        self.assertEqual(extract_relation_candidates("What is Python?", SENTENCE_QUESTION), [])


class TestUnderstandingEngineCases(unittest.TestCase):
    """Cases A-H required by the task spec."""

    def setUp(self):
        self.engine = UnderstandingEngine()

    def test_case_a_is_a_statement(self):
        result = self.engine.understand("Python is a programming language.")
        self.assertIsInstance(result, UnderstandingResult)
        self.assertEqual(result.sentence_type, SENTENCE_STATEMENT)
        self.assertEqual(result.language, LANGUAGE_ENGLISH)
        self.assertIn("Python", entity_texts(result))
        self.assertIn("programming language", entity_texts(result))
        self.assertEqual(len(result.relations), 1)
        rel = result.relations[0]
        self.assertEqual(rel.subject, "Python")
        self.assertEqual(rel.relation, "IS_A")
        self.assertEqual(rel.object, "programming language")
        self.assertEqual(result.facts, [])
        self.assertGreater(result.confidence, 0.5)

    def test_case_b_uses_statement(self):
        result = self.engine.understand("Python uses indentation.")
        self.assertEqual(result.sentence_type, SENTENCE_STATEMENT)
        self.assertEqual(len(result.relations), 1)
        rel = result.relations[0]
        self.assertEqual((rel.subject, rel.relation, rel.object), ("Python", "USES", "indentation"))
        self.assertIn("Python", entity_texts(result))
        self.assertIn("indentation", entity_texts(result))

    def test_case_c_question(self):
        result = self.engine.understand("What is Python?")
        self.assertEqual(result.sentence_type, SENTENCE_QUESTION)
        self.assertEqual(result.relations, [])
        self.assertIn("python", [t.lower() for t in entity_texts(result)])

    def test_case_d_command(self):
        result = self.engine.understand("Teach me Python.")
        self.assertEqual(result.sentence_type, SENTENCE_COMMAND)
        self.assertEqual(result.relations, [])
        texts_lower = [t.lower() for t in entity_texts(result)]
        self.assertIn("python", texts_lower)
        self.assertNotIn("teach", texts_lower)

    def test_case_e_empty_input(self):
        result = self.engine.understand("")
        self.assertEqual(result.sentence_type, SENTENCE_UNKNOWN)
        self.assertEqual(result.language, LANGUAGE_UNKNOWN)
        self.assertEqual(result.tokens, [])
        self.assertEqual(result.entities, [])
        self.assertEqual(result.relations, [])
        self.assertEqual(result.confidence, 0.0)
        self.assertIn("empty_input", result.warnings)

        # None must be handled exactly like empty input, never raise.
        result_none = self.engine.understand(None)
        self.assertEqual(result_none.sentence_type, SENTENCE_UNKNOWN)
        self.assertIn("empty_input", result_none.warnings)

    def test_case_f_mixed_punctuation(self):
        result = self.engine.understand("   Python??!! ... is--- a   programming_language!!!   ")
        # Must not crash, must still produce a structured result.
        self.assertIsInstance(result, UnderstandingResult)
        self.assertIn(result.sentence_type, (SENTENCE_QUESTION, SENTENCE_STATEMENT, SENTENCE_UNKNOWN))
        self.assertIsInstance(result.tokens, list)
        self.assertGreaterEqual(len(result.tokens), 1)

    def test_case_g_persian_text(self):
        result = self.engine.understand("پایتون یک زبان برنامه‌نویسی است.")
        self.assertEqual(result.language, LANGUAGE_PERSIAN)
        self.assertIsInstance(result, UnderstandingResult)
        self.assertGreaterEqual(len(result.tokens), 1)
        # No crash and a structured (possibly low-confidence) result is
        # the bar for this stage's Persian support - not full Persian
        # relation extraction.
        self.assertGreaterEqual(result.confidence, 0.0)

    def test_case_h_existing_ael_input_untouched(self):
        # The Understanding Engine must not interfere with AEL - Core
        # routes AEL lines to the Parser/AEL interpreter exactly as
        # before; this simply confirms the Understanding Engine itself
        # doesn't choke on AEL-shaped text if ever handed it directly.
        result = self.engine.understand('TEACH Python IS Programming Language')
        self.assertIsInstance(result, UnderstandingResult)
        self.assertIsInstance(result.tokens, list)
        self.assertGreaterEqual(len(result.tokens), 1)

    def test_to_dict_is_json_shaped(self):
        result = self.engine.understand("Python is a programming language.")
        d = result.to_dict()
        for key in ("original_text", "normalized_text", "language", "tokens", "sentence_type",
                    "entities", "relations", "facts", "confidence", "warnings"):
            self.assertIn(key, d)


class TestCoreIntegration(unittest.TestCase):
    """Confirms the Understanding Engine is wired into Core as an
    additional capability without breaking the existing AEL pipeline
    or conversational flow (case H, end-to-end)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ael_teach_and_ask_still_work(self):
        teach_reply = self.core.process_input('TEACH Python IS Programming Language')
        self.assertIn("[AEL OK]", teach_reply)

        ask_reply = self.core.process_input("ASK Python")
        self.assertIn("Programming Language", ask_reply)

    def test_conversation_fallback_still_works(self):
        # Deliberately avoids substrings of any seeded skill keyword
        # (e.g. "hi" inside "something") so this exercises the honest
        # no-knowledge fallback, not the seeded "greet" skill.
        reply = self.core.process_input("qwerty zzznoxyzzz unmapped concept")
        self.assertIn("I don't have enough information", reply)

    def test_understand_is_available_and_side_effect_free(self):
        before = self.core.memory.counts()
        result = self.core.understand("Python is a programming language.")
        self.assertIsInstance(result, UnderstandingResult)
        self.assertEqual(result.relations[0].relation, "IS_A")
        after = self.core.memory.counts()
        # Calling understand() must not write anything to memory/knowledge.
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
