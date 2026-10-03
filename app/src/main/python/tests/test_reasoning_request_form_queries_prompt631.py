"""Prompt 631 - Section 3 (Reasoning): request-form questions such as
"Tell me about Python", "Explain Python", "What's Python?" and polite
prefixes now reach the same knowledge lookup as "What is Python?"
instead of falling through to a generic lookup of the whole sentence."""
import os
import sys
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from reasoning.reasoning_engine import ReasoningEngine
from reasoning.reasoning_result import STATUS_ANSWERED, STATUS_UNKNOWN
from reasoning.query_parsing import (
    parse_query, INTENT_WHAT_IS, INTENT_GENERIC, INTENT_VERIFY_RELATION,
    INTENT_VERIFY_IS_A, INTENT_RELATION_QUERY,
)
from core.core import Core


def _engine():
    memory = MemorySystem(tempfile.mktemp(suffix=".db"))
    knowledge = KnowledgeSystem(memory)
    return ReasoningEngine(knowledge), knowledge


class TestParsing(unittest.TestCase):
    def test_request_forms_become_what_is(self):
        for text in ("Tell me about Python", "Explain Python", "Define Python",
                     "Describe Python", "What's Python?", "Whats Python",
                     "Tell me more about Python", "Tell me what Python is",
                     "Can you tell me about Python?", "Could you explain Python",
                     "Please explain Python", "Kindly define Python",
                     "please, what is Python?", "EXPLAIN Python"):
            p = parse_query(text, request_forms=True)
            self.assertEqual((p.intent, p.subject), (INTENT_WHAT_IS, "Python"), text)
            self.assertEqual(p.raw_text, text)

    def test_multiword_subject_and_reference_word(self):
        self.assertEqual(parse_query("Explain programming language", request_forms=True).subject, "programming language")
        self.assertEqual(parse_query("Describe it", request_forms=True).subject, "it")

    def test_polite_prefix_on_existing_patterns(self):
        p = parse_query("Please does Python use indentation?", request_forms=True)
        self.assertEqual((p.intent, p.relation, p.object), (INTENT_VERIFY_RELATION, "USES", "indentation"))
        self.assertEqual(parse_query("Please, is Python a language", request_forms=True).intent, INTENT_VERIFY_IS_A)
        self.assertEqual(parse_query("please what is Python used for", request_forms=True).relation, "USED_FOR")

    def test_backward_compatible(self):
        self.assertEqual(parse_query("What is Python?").intent, INTENT_WHAT_IS)
        self.assertEqual(parse_query("What does Python use?").intent, INTENT_RELATION_QUERY)
        self.assertEqual(parse_query("Python").intent, INTENT_GENERIC)
        self.assertEqual(parse_query("Python").subject, "Python")
        self.assertEqual(parse_query("").intent, INTENT_GENERIC)
        self.assertEqual(parse_query(None).subject, "")
        # bare verb / bare politeness word / politeness word as subject: unchanged
        for text in ("Explain", "Please", "Please is a word", "Tell me about"):
            for flag in (False, True):
                self.assertEqual(parse_query(text, request_forms=flag).intent, INTENT_GENERIC, text)
        self.assertEqual(parse_query("Please is a word", request_forms=True).subject, "Please is a word")

    def test_default_parse_is_unchanged_without_opt_in(self):
        for text in ("Tell me about Python", "Explain Python", "What's Python?", "Please explain Python"):
            p = parse_query(text)
            self.assertEqual(p.intent, INTENT_GENERIC, text)
            self.assertEqual(p.subject, text.rstrip("?"))


class TestEngineIntegration(unittest.TestCase):
    def test_request_form_answers_like_what_is(self):
        reasoning, knowledge = _engine()
        knowledge.learn("Python", "a general-purpose programming language")
        baseline = reasoning.reason("What is Python?")
        for text in ("Tell me about Python", "Explain Python", "What's Python?",
                     "Please define Python"):
            r = reasoning.reason(text, request_forms=True)
            self.assertNotEqual(reasoning.reason(text).status, STATUS_ANSWERED, text)  # default unchanged
            self.assertEqual(r.status, STATUS_ANSWERED, text)
            self.assertEqual(r.answer, baseline.answer, text)

    def test_unknown_subject_stays_unknown_never_fabricated(self):
        reasoning, _ = _engine()
        r = reasoning.reason("Tell me about Zorblax", request_forms=True)
        self.assertEqual(r.status, STATUS_UNKNOWN)
        self.assertIsNone(r.answer)

    def test_reference_word_resolves_via_context(self):
        tmp = tempfile.mkdtemp()
        core = Core(memory_db_path=os.path.join(tmp, "c.db"),
                    skill_definitions_dir=os.path.join(tmp, "s"))
        core.knowledge.learn("Python", "a programming language")
        core.understand("Python is a programming language.")
        r = core.reason("Explain it")
        self.assertEqual(r.status, STATUS_ANSWERED)

    def test_core_reason_entry_uses_request_forms_but_process_input_unchanged(self):
        tmp = tempfile.mkdtemp()
        core = Core(memory_db_path=os.path.join(tmp, "c.db"),
                    skill_definitions_dir=os.path.join(tmp, "s"))
        core.knowledge.learn("Rust", "A systems programming language.")
        r = core.reason("Tell me about Rust")
        self.assertEqual(r.status, STATUS_ANSWERED)
        self.assertIn("systems programming language", r.answer)
        # the conversational path keeps its existing wording
        self.assertEqual(core.process_input("Tell me about Rust"),
                         "Here's what I know about 'Rust': A systems programming language.")

    def test_does_not_write_knowledge(self):
        reasoning, knowledge = _engine()
        knowledge.learn("Python", "a language")
        before = len(knowledge.list_all()) if hasattr(knowledge, "list_all") else None
        reasoning.reason("Explain Python", request_forms=True)
        reasoning.reason("Tell me about Zorblax", request_forms=True)
        if before is not None:
            self.assertEqual(len(knowledge.list_all()), before)
        self.assertIsNone(knowledge.find_by_name_case_insensitive("Zorblax"))


if __name__ == "__main__":
    unittest.main()
