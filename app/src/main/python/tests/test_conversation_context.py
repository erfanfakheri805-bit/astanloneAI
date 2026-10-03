"""
Tests for the Conversation Context / Context Resolution stage.

Run directly:
    python -m unittest tests.test_conversation_context -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)

Covers TEST A-H from the stage spec, plus a few focused unit tests for
the ConversationContext and reference-resolution building blocks on
their own.
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.conversation_context import ConversationContext, DEFAULT_CONTEXT_SIZE
from context.reference_resolution import resolve_reference, resolve_context_references
from understanding.engine import UnderstandingEngine
from core.core import Core


def entity_texts(result):
    return [e["text"] for e in result.entities]


def relation_tuples(result):
    return [(r.subject, r.relation, r.object) for r in result.relations]


class TestConversationContextBasics(unittest.TestCase):
    def setUp(self):
        self.engine = UnderstandingEngine()

    def test_add_and_get_recent_context_is_structured(self):
        context = ConversationContext()
        result = self.engine.understand("Python is a programming language.")
        context.add_understanding(result)

        recent = context.get_recent_context()
        self.assertEqual(len(recent), 1)
        entry = recent[0]
        for key in ("id", "timestamp", "input_text", "normalized_text", "language",
                    "sentence_type", "entities", "relations", "confidence", "importance", "source"):
            self.assertIn(key, entry)
        self.assertEqual(entry["input_text"], "Python is a programming language.")

    def test_context_window_is_bounded(self):
        # TEST E: bounded short-term context.
        context = ConversationContext(max_size=3)
        for i in range(10):
            result = self.engine.understand(f"Concept{i} is a thing.")
            context.add_understanding(result)
        self.assertEqual(len(context), 3)
        recent = context.get_recent_context()
        self.assertEqual(len(recent), 3)
        # Only the most recent 3 inputs should have survived.
        self.assertEqual(
            [e["input_text"] for e in recent],
            ["Concept7 is a thing.", "Concept8 is a thing.", "Concept9 is a thing."],
        )

    def test_default_context_size_is_small_and_configurable(self):
        self.assertGreater(DEFAULT_CONTEXT_SIZE, 0)
        self.assertLessEqual(DEFAULT_CONTEXT_SIZE, 50)
        self.assertEqual(ConversationContext(max_size=1).max_size, 1)

    def test_reset_clears_short_term_context(self):
        # TEST C: reset context.
        context = ConversationContext()
        context.add_understanding(self.engine.understand("Python is a programming language."))
        self.assertEqual(len(context), 1)
        context.reset()
        self.assertEqual(len(context), 0)
        self.assertEqual(context.get_recent_context(), [])

    def test_importance_is_higher_for_informative_input(self):
        low = self.engine.understand("Hello.")
        context = ConversationContext()
        entry_low = context.add_understanding(low)

        context.reset()
        high = self.engine.understand("Remember that this project uses SQLite.")
        entry_high = context.add_understanding(high)

        self.assertLess(entry_low.importance, entry_high.importance)


class TestReferenceResolutionUnit(unittest.TestCase):
    def setUp(self):
        self.engine = UnderstandingEngine()
        self.context = ConversationContext()

    def test_non_reference_word_returns_none(self):
        self.assertIsNone(resolve_reference("Python", self.context))

    def test_no_candidates_is_ambiguous(self):
        resolution = resolve_reference("it", self.context)
        self.assertTrue(resolution.ambiguous)
        self.assertIsNone(resolution.resolved_entity)
        self.assertEqual(resolution.reason, "no_candidates")

    def test_generic_reference_resolves_via_semantic_match(self):
        result = self.engine.understand("Python is a programming language.")
        self.context.add_understanding(result)
        resolution = resolve_reference("the language", self.context)
        self.assertFalse(resolution.ambiguous)
        self.assertEqual(resolution.resolved_entity, "Python")


class TestContextAwareUnderstanding(unittest.TestCase):
    """TEST A, B: reference resolution feeding context-aware understanding."""

    def setUp(self):
        self.engine = UnderstandingEngine()
        self.context = ConversationContext()

    def test_case_a_pronoun_resolves_to_recent_subject(self):
        first = self.engine.understand("Python is a programming language.", context=self.context)
        self.context.add_understanding(first)

        second = self.engine.understand("It uses indentation.", context=self.context)

        self.assertEqual(relation_tuples(second), [("Python", "USES", "indentation")])
        self.assertIn("Python", entity_texts(second))
        self.assertNotIn("it", [t.lower() for t in entity_texts(second)])

        resolved_traces = [t for t in second.context_resolutions if not t["ambiguous"]]
        self.assertTrue(any(t["resolved_entity"] == "Python" for t in resolved_traces))

    def test_case_b_ambiguous_reference_is_not_guessed(self):
        self.context.add_understanding(self.engine.understand("Python uses indentation.", context=self.context))
        self.context.add_understanding(self.engine.understand("Java uses braces.", context=self.context))

        # "It has fans." does match the HAS relation pattern (subject
        # "It"), unlike "It is popular." - this is the case that
        # actually exercises ambiguity handling rather than simply
        # producing no relation candidate to begin with.
        third = self.engine.understand("It has fans.", context=self.context)

        # No relation should have been fabricated for the ambiguous "it" -
        # the candidate relation is dropped entirely, not persisted
        # under either guessed subject.
        self.assertEqual(third.relations, [])
        self.assertTrue(any(t["ambiguous"] for t in third.context_resolutions))

    def test_context_none_skips_resolution_entirely(self):
        # Backwards compatibility: no context given -> behaves exactly
        # like the previous stage (reference words pass through as-is).
        result = self.engine.understand("It uses indentation.")
        self.assertEqual(relation_tuples(result), [("It", "USES", "indentation")])
        self.assertEqual(result.context_resolutions, [])


class TestCoreContextIntegration(unittest.TestCase):
    """TEST A-H exercised end-to-end through Core, as a caller would
    actually use this stage."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_case_a_context_aware_learning_stores_resolved_subject(self):
        self.core.learn_from_text("Python is a programming language.")
        learning_result = self.core.learn_from_text("It uses indentation.")

        self.assertIn(
            {"subject": "Python", "relation": "USES", "object": "indentation",
             "confidence": learning_result.learned_items[0]["confidence"], "input_type": "RELATIONSHIP"},
            learning_result.learned_items,
        )
        stored = self.core.learning.recall("Python")
        relation_types = [(r["relation_type"], r["to_name"]) for r in stored["relationships"]["outgoing"]]
        self.assertIn(("USES", "indentation"), relation_types)
        # And never a bogus concept literally named "it" / "It".
        self.assertIsNone(self.core.knowledge.get("it"))
        self.assertIsNone(self.core.knowledge.find_by_name_case_insensitive("it"))

    def test_case_b_ambiguous_reference_detected_end_to_end(self):
        self.core.learn_from_text("Python uses indentation.")
        self.core.learn_from_text("Java uses braces.")
        learning_result = self.core.learn_from_text("It has fans.")

        self.assertEqual(learning_result.learned_items, [])
        self.assertIsNone(self.core.knowledge.get("it"))
        self.assertIsNone(self.core.knowledge.find_by_name_case_insensitive("it"))

    def test_case_c_reset_stops_resolving_references(self):
        self.core.learn_from_text("Python is a programming language.")
        self.core.reset_context()

        result = self.core.understand("It uses indentation.")
        # With no context to resolve against, "It" is left unresolved
        # (and therefore not persisted as a relation subject at all).
        self.assertEqual(result.relations, [])

    def test_case_d_persistent_knowledge_survives_context_reset(self):
        self.core.learn_from_text("Python is a programming language.")
        before = self.core.learning.recall("Python")
        self.assertIsNotNone(before)

        self.core.reset_context()

        after = self.core.learning.recall("Python")
        self.assertIsNotNone(after)
        self.assertEqual(before["name"], after["name"])
        self.assertEqual(self.core.get_recent_context(), [])

    def test_case_e_context_is_bounded_through_core(self):
        for i in range(DEFAULT_CONTEXT_SIZE + 5):
            self.core.understand(f"Concept{i} is a thing.")
        self.assertLessEqual(len(self.core.get_recent_context()), self.core.context.max_size)

    def test_case_f_ael_commands_still_work(self):
        reply = self.core.process_input("TEACH Python IS Programming Language")
        self.assertIn("[AEL OK]", reply)
        ask_reply = self.core.process_input("ASK Python")
        self.assertIn("Programming Language", ask_reply)
        # AEL never touches short-term conversational context.
        self.assertEqual(self.core.get_recent_context(), [])

    def test_case_g_existing_natural_language_learning_still_works(self):
        learning_result = self.core.learn_from_text("Python is a programming language.")
        self.assertIn(
            {"subject": "Python", "relation": "IS_A", "object": "programming language",
             "confidence": learning_result.learned_items[0]["confidence"], "input_type": "FACT"},
            learning_result.learned_items,
        )

    def test_case_h_malformed_input_does_not_crash(self):
        self.core.understand("")
        self.core.understand(None)
        self.core.understand("   !!! ??? ---   ")
        result = self.core.understand("It.")
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
