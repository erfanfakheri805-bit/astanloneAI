"""
Tests for Prompt 419 - Learned Meaning in Message Understanding.

`DeterministicFallbackBackend.understand()` (language_intelligence/
deterministic_fallback_backend.py) can optionally be given a
`MeaningResolver` (Prompt 418, meaning_resolution.py). When it is, the
`LanguageUnderstandingResult` it returns carries a `learned_meanings`
list: one `MeaningResolutionResult.to_dict()` (Prompt 418) per candidate
expression already found by the existing Understanding Engine
(`entities` - reused unchanged). Nothing here re-implements the
Understanding Engine, the Language Learning Store (Prompt 416), the
Language Relationship Store (Prompt 417) or the Meaning Resolver
(Prompt 418) - this stage only wires them together.

Run directly:
    python -m unittest tests.test_learned_meaning_in_understanding -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from understanding.language_detection import LANGUAGE_ENGLISH, LANGUAGE_UNKNOWN

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import LanguageLearningStore, ITEM_TYPE_WORD
from language_intelligence.language_relationships import LanguageRelationshipStore
from language_intelligence.meaning_resolution import MeaningResolver, STATUS_RESOLVED, STATUS_NOT_FOUND
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.language_understanding_result import LanguageUnderstandingResult

from core.core import Core


class _BaseTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + the composed Prompt 416-418 stores,
    a MeaningResolver over them, and a DeterministicFallbackBackend
    wired to that resolver - the exact composition Core itself builds
    (see core/core.py's __init__)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.knowledge = KnowledgeSystem(self.memory)
        self.items = LanguageLearningStore(self.memory)
        self.relationships = LanguageRelationshipStore(self.memory, self.items, self.knowledge)
        self.resolver = MeaningResolver(self.items, self.relationships, knowledge=self.knowledge)
        self.engine = UnderstandingEngine()
        self.backend = DeterministicFallbackBackend(self.engine, meaning_resolver=self.resolver)
        self.lic = LanguageIntelligenceCore(backend=self.backend)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _entry_for(self, learned_meanings, expression):
        matches = [e for e in learned_meanings if e["expression"] == expression]
        self.assertEqual(len(matches), 1, f"expected exactly one entry for {expression!r}")
        return matches[0]


class TestKnownLearnedExpressionExposesItsMeaning(_BaseTestCase):
    """1. A message containing a known learned expression exposes its
    learned meaning."""

    def test_learned_word_in_a_message_is_resolved(self):
        self.items.learn_item(
            "english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a programming language"},
        )
        result = self.lic.understand("Python is a programming language.")
        entry = self._entry_for(result.learned_meanings, "Python")
        self.assertEqual(entry["status"], STATUS_RESOLVED)
        self.assertEqual(entry["meanings"][0]["meaning"], {"gloss": "a programming language"})

    def test_result_carries_the_new_field_in_to_dict(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning="a language")
        result = self.lic.understand("Python is a programming language.")
        as_dict = result.to_dict()
        self.assertIn("learned_meanings", as_dict)
        self.assertTrue(any(e["expression"] == "Python" for e in as_dict["learned_meanings"]))


class TestOriginalMessageIsUnchanged(_BaseTestCase):
    """2. The original user message remains unchanged."""

    def test_original_input_is_verbatim_despite_learned_meaning_lookup(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning="a language")
        raw = "  Python   is a   programming language.  "
        result = self.lic.understand(raw)
        self.assertEqual(result.original_input, raw)

    def test_no_translation_or_rewriting_happens(self):
        self.items.learn_item(
            "english", ITEM_TYPE_WORD, "hello", meaning={"gloss": "سلام", "translation": "سلام"},
        )
        result = self.lic.understand("Hello there friend.")
        self.assertEqual(result.original_input, "Hello there friend.")
        self.assertNotIn("سلام", result.normalized_input)


class TestUnknownExpressionRemainsUnresolved(_BaseTestCase):
    """3. An unknown expression remains unresolved - never presented as
    understood, never given an invented meaning."""

    def test_unknown_expression_is_marked_not_found(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "bagelization", meaning="a made-up word")
        result = self.lic.understand("Bagelization happens quickly.")
        entry = self._entry_for(result.learned_meanings, "happens")
        self.assertEqual(entry["status"], STATUS_NOT_FOUND)
        self.assertEqual(entry["meanings"], [])
        self.assertFalse(entry["ambiguous"])

    def test_a_known_item_with_no_stored_meaning_is_also_not_found(self):
        # learn_item requires SOME field; teach it, then blank the
        # meaning back out via a second call - still a valid learned
        # item, just with nothing meaning-bearing stored (see
        # meaning_resolution.py's REASON_NO_LEARNED_MEANING).
        self.items.learn_item("english", ITEM_TYPE_WORD, "widget", meaning={"gloss": "x"})
        self.items.learn_item("english", ITEM_TYPE_WORD, "widget", meaning={})
        result = self.lic.understand("The widget broke yesterday.")
        entry = self._entry_for(result.learned_meanings, "widget")
        self.assertEqual(entry["status"], STATUS_NOT_FOUND)
        self.assertEqual(entry["meanings"], [])

    def test_entities_still_lists_the_unknown_expression(self):
        # Existing deterministic behavior (candidate extraction) is
        # unaffected by resolution failing to find anything.
        result = self.lic.understand("Bagelization happens quickly.")
        self.assertTrue(any(e["text"] == "happens" for e in result.entities))


class TestLanguageLocaleIsRespected(_BaseTestCase):
    """4. Language/locale is respected - the same written form in two
    languages is never merged into one meaning."""

    def test_only_the_detected_languages_meaning_is_attached(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "mint", meaning={"gloss": "an herb"})
        self.items.learn_item("german", ITEM_TYPE_WORD, "mint", meaning={"gloss": "coin factory"})
        result = self.lic.understand("I found mint in the garden.")
        self.assertEqual(result.detected_language, LANGUAGE_ENGLISH)
        entry = self._entry_for(result.learned_meanings, "mint")
        self.assertEqual(entry["status"], STATUS_RESOLVED)
        self.assertEqual(len(entry["meanings"]), 1)
        self.assertEqual(entry["meanings"][0]["language"], "english")
        self.assertEqual(entry["meanings"][0]["meaning"], {"gloss": "an herb"})

    def test_undetermined_language_searches_every_language(self):
        # No letters at all -> LANGUAGE_UNKNOWN; entity extraction still
        # yields a term from the digits/punctuation-free fallback path
        # only when there is a word-like token, so use a tiny custom
        # lookup directly against the backend's own helper instead of
        # relying on a specific sentence shape.
        self.items.learn_item("german", ITEM_TYPE_WORD, "mint", meaning={"gloss": "coin factory"})
        learned_meanings, warnings = self.backend._resolve_learned_meanings(
            [{"text": "mint", "status": "candidate"}], LANGUAGE_UNKNOWN, [],
        )
        self.assertEqual(len(learned_meanings), 1)
        self.assertEqual(learned_meanings[0]["status"], STATUS_RESOLVED)
        self.assertIsNone(learned_meanings[0]["language"])
        self.assertEqual(learned_meanings[0]["meanings"][0]["language"], "german")


class TestLearnedConfidenceAndContextArePreserved(_BaseTestCase):
    """5. Learned confidence/context is preserved."""

    def test_confidence_source_and_context_carry_through(self):
        self.items.learn_item(
            "english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"},
            confidence=0.75, source="user", source_context="taught during onboarding",
            learning_method="manual",
        )
        result = self.lic.understand("Python is a programming language.")
        entry = self._entry_for(result.learned_meanings, "Python")
        meaning = entry["meanings"][0]
        self.assertEqual(meaning["confidence"], 0.75)
        self.assertEqual(meaning["source"], "user")
        self.assertEqual(meaning["source_context"], "taught during onboarding")
        self.assertEqual(meaning["learning_method"], "manual")


class TestMultipleLearnedExpressionsInOneMessage(_BaseTestCase):
    """6. Multiple learned expressions in one message can be represented
    without losing existing understanding data."""

    def test_two_learned_expressions_both_resolve(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        self.items.learn_item(
            "english", ITEM_TYPE_WORD, "programming language",
            meaning={"gloss": "a formal instruction language"},
        )
        result = self.lic.understand("Python is a programming language.")
        python_entry = self._entry_for(result.learned_meanings, "Python")
        phrase_entry = self._entry_for(result.learned_meanings, "programming language")
        self.assertEqual(python_entry["status"], STATUS_RESOLVED)
        self.assertEqual(phrase_entry["status"], STATUS_RESOLVED)
        # existing understanding fields are untouched
        self.assertEqual(len(result.entities), 2)
        self.assertTrue(any(e["text"] == "Python" for e in result.entities))
        self.assertTrue(any(e["text"] == "programming language" for e in result.entities))
        self.assertIsInstance(result, LanguageUnderstandingResult)

    def test_learned_meanings_has_no_duplicate_expressions(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "widget", meaning={"gloss": "a thing"})
        result = self.lic.understand("A widget is a widget, the widget said.")
        expressions = [e["expression"].lower() for e in result.learned_meanings]
        self.assertEqual(len(expressions), len(set(expressions)))


class TestExistingDeterministicUnderstandingStillWorksWithoutResolver(unittest.TestCase):
    """7. Existing deterministic understanding still works when no
    learned meaning is available (no resolver configured)."""

    def test_no_resolver_reproduces_the_pre_419_shape(self):
        backend = DeterministicFallbackBackend(UnderstandingEngine())
        lic = LanguageIntelligenceCore(backend=backend)
        result = lic.understand("Python is a programming language.")
        self.assertEqual(result.learned_meanings, [])
        self.assertTrue(any(e["text"] == "Python" for e in result.entities))

    def test_no_candidate_expressions_yields_empty_learned_meanings(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemorySystem(os.path.join(tmp, "memory.db"))
            knowledge = KnowledgeSystem(memory)
            items = LanguageLearningStore(memory)
            relationships = LanguageRelationshipStore(memory, items, knowledge)
            resolver = MeaningResolver(items, relationships, knowledge=knowledge)
            backend = DeterministicFallbackBackend(UnderstandingEngine(), meaning_resolver=resolver)
            lic = LanguageIntelligenceCore(backend=backend)
            result = lic.understand("")
            self.assertEqual(result.learned_meanings, [])

    def test_a_failing_resolver_is_caught_and_warned_never_raised(self):
        class _ExplodingResolver:
            def resolve(self, expression, language=None):
                raise RuntimeError("boom")

        backend = DeterministicFallbackBackend(
            UnderstandingEngine(), meaning_resolver=_ExplodingResolver(),
        )
        lic = LanguageIntelligenceCore(backend=backend)
        result = lic.understand("Python is a programming language.")
        self.assertEqual(result.learned_meanings, [])
        self.assertTrue(any(w.startswith("learned_meaning_lookup_error") for w in result.warnings))
        # existing understanding is otherwise unaffected
        self.assertTrue(any(e["text"] == "Python" for e in result.entities))


class TestBackwardCompatibilityWithPromptsFourSixteenToFourEighteen(_BaseTestCase):
    """8. Existing Prompt 416-418 tests remain compatible - Prompt 419
    adds a caller of MeaningResolver.resolve(), never a change to its
    behavior, and no change at all to LanguageLearningStore or
    LanguageRelationshipStore."""

    def test_resolver_used_directly_behaves_exactly_as_before(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"})
        direct = self.resolver.resolve("hello", "english")
        self.assertEqual(direct.status, STATUS_RESOLVED)
        self.assertEqual(direct.meanings[0]["meaning"], {"gloss": "a greeting"})

    def test_store_and_relationship_apis_are_untouched(self):
        item = self.items.learn_item("english", ITEM_TYPE_WORD, "hello", meaning="greeting")
        self.assertEqual(self.items.get_item("english", ITEM_TYPE_WORD, "hello")["meaning"], "greeting")
        self.assertEqual(item["language"], "english")


class TestExistingConversationProcessingRemainsCompatible(unittest.TestCase):
    """9. Existing conversation processing remains compatible - Core's
    real conversation path still replies normally, and now records
    learned meanings on self.last_language_understanding, with the
    reply text itself completely unaffected (the deterministic backend
    still never generates text - see response_generation.py)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.core = Core(memory_db_path=os.path.join(self._tmpdir.name, "memory.db"))

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_wires_the_same_meaning_resolver_into_its_backend(self):
        self.assertIs(self.core.language_intelligence.backend._meaning_resolver,
                       self.core.meaning_resolver)

    def test_ordinary_conversation_is_unaffected(self):
        reply = self.core.process_input("Tell me about widgets.")
        self.assertIsInstance(reply, str)
        self.assertTrue(reply)
        understanding = self.core.get_last_language_understanding()
        self.assertIsInstance(understanding, LanguageUnderstandingResult)
        # nothing taught yet - no candidate resolves to a learned meaning
        self.assertFalse(any(e["status"] == STATUS_RESOLVED for e in understanding.learned_meanings))

    def test_a_learned_word_shows_up_on_the_next_turn(self):
        self.core.learn_language_item("english", ITEM_TYPE_WORD, "python", meaning="a language")
        self.core.process_input("Python is a programming language.")
        understanding = self.core.get_last_language_understanding()
        matches = [e for e in understanding.learned_meanings if e["expression"] == "Python"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["status"], STATUS_RESOLVED)

    def test_process_input_still_returns_reply_text_unchanged_in_shape(self):
        # Same call, teaching does not change the fact that this backend
        # defers reply generation to the existing pipeline.
        self.core.learn_language_item("english", ITEM_TYPE_WORD, "python", meaning="a language")
        reply = self.core.process_input("Python is a programming language.")
        self.assertIsInstance(reply, str)
        response = self.core.get_last_language_response()
        from language_intelligence.response_generation import STATUS_DEFERRED
        self.assertEqual(response.status, STATUS_DEFERRED)


if __name__ == "__main__":
    unittest.main()
