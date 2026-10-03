"""
Tests for Prompt 416 - Language Learning Foundation.

`LanguageLearningStore` (language_intelligence/language_learning_store.py)
is a small, structured foundation for recording and retrieving learned
language items (words, phrases, sentence patterns) - one language/locale at
a time, backed by ONE more MemorySystem table (not a second memory system),
and reachable from Core via two thin passthrough methods
(learn_language_item / get_language_item).

Run directly:
    python -m unittest tests.test_language_learning_store -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from language_intelligence.language_learning_store import (
    LanguageLearningStore, ITEM_TYPE_WORD, ITEM_TYPE_PHRASE, ITEM_TYPE_PATTERN,
)
from core.core import Core


def _store():
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    return LanguageLearningStore(memory), memory


class TestRecordingALanguageItem(unittest.TestCase):
    """1. A language item can be learned."""

    def test_learn_item_returns_a_dict_with_the_given_fields(self):
        store, _memory = _store()
        item = store.learn_item(
            "english", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"},
            examples=["Hello, how are you?"], confidence=0.9, source="user",
            source_context="the user said hello", learning_method="manual",
        )
        self.assertEqual(item["language"], "english")
        self.assertEqual(item["item_type"], ITEM_TYPE_WORD)
        self.assertEqual(item["key"], "hello")
        self.assertEqual(item["meaning"], {"gloss": "a greeting"})
        self.assertEqual(item["examples"], ["Hello, how are you?"])
        self.assertEqual(item["confidence"], 0.9)
        self.assertEqual(item["source"], "user")
        self.assertEqual(item["source_context"], "the user said hello")
        self.assertEqual(item["learning_method"], "manual")
        self.assertEqual(item["version"], 1)
        self.assertIsInstance(item["id"], int)

    def test_phrase_and_pattern_item_types_are_accepted(self):
        store, _memory = _store()
        phrase = store.learn_item("english", ITEM_TYPE_PHRASE, "good morning")
        pattern = store.learn_item("english", ITEM_TYPE_PATTERN, "___ is a ___")
        self.assertEqual(phrase["item_type"], ITEM_TYPE_PHRASE)
        self.assertEqual(pattern["item_type"], ITEM_TYPE_PATTERN)

    def test_a_custom_item_type_beyond_the_suggested_three_is_accepted(self):
        # The system is language-agnostic and open-ended - it must not
        # reject a future learning module's own item_type vocabulary.
        store, _memory = _store()
        item = store.learn_item("german", "affix", "ge-")
        self.assertEqual(item["item_type"], "affix")

    def test_missing_language_is_rejected(self):
        store, _memory = _store()
        with self.assertRaises(ValueError):
            store.learn_item("", ITEM_TYPE_WORD, "hello")
        with self.assertRaises(ValueError):
            store.learn_item("unknown", ITEM_TYPE_WORD, "hello")

    def test_missing_key_is_rejected(self):
        store, _memory = _store()
        with self.assertRaises(ValueError):
            store.learn_item("english", ITEM_TYPE_WORD, "")


class TestRetrievingALearnedItem(unittest.TestCase):
    """2. A learned item can be retrieved."""

    def test_get_item_returns_what_was_learned(self):
        store, _memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "cat", meaning={"gloss": "a small feline"})
        retrieved = store.get_item("english", ITEM_TYPE_WORD, "cat")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["key"], "cat")
        self.assertEqual(retrieved["meaning"], {"gloss": "a small feline"})

    def test_get_item_returns_none_for_an_unlearned_item(self):
        store, _memory = _store()
        self.assertIsNone(store.get_item("english", ITEM_TYPE_WORD, "nonexistent"))

    def test_retrieval_is_insensitive_to_surrounding_whitespace_and_case(self):
        # Deterministic identity match: same text, different incidental
        # formatting, resolves to the same row.
        store, _memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "Hello")
        self.assertIsNotNone(store.get_item("english", ITEM_TYPE_WORD, "  hello  "))


class TestLanguageLocaleAssociation(unittest.TestCase):
    """3. Language/locale is preserved."""

    def test_the_stored_language_is_returned(self):
        store, _memory = _store()
        item = store.learn_item("french", ITEM_TYPE_WORD, "bonjour")
        self.assertEqual(item["language"], "french")
        self.assertEqual(store.get_item("french", ITEM_TYPE_WORD, "bonjour")["language"], "french")

    def test_language_aliases_canonicalize_to_the_same_entry(self):
        # Reuses language_context.canonical_language (Prompt 401) - "fa"
        # and "persian" name the same language, so they share one item.
        store, _memory = _store()
        store.learn_item("fa", ITEM_TYPE_WORD, "سلام", meaning={"gloss": "hello"})
        via_alias = store.get_item("persian", ITEM_TYPE_WORD, "سلام")
        self.assertIsNotNone(via_alias)
        self.assertEqual(via_alias["language"], "persian")
        self.assertEqual(via_alias["meaning"], {"gloss": "hello"})


class TestMeaningContextIsPreserved(unittest.TestCase):
    """4. Storing structured meaning/context information."""

    def test_arbitrary_structured_meaning_round_trips(self):
        store, _memory = _store()
        meaning = {
            "gloss": "a greeting",
            "translations": {"persian": "سلام", "spanish": "hola"},
            "part_of_speech": "interjection",
        }
        store.learn_item("english", ITEM_TYPE_WORD, "hello", meaning=meaning)
        retrieved = store.get_item("english", ITEM_TYPE_WORD, "hello")
        self.assertEqual(retrieved["meaning"], meaning)

    def test_relationships_and_examples_round_trip(self):
        store, _memory = _store()
        relationships = [{"type": "synonym_of", "target": "hi"}]
        examples = ["Hello there!", "She said hello."]
        item = store.learn_item(
            "english", ITEM_TYPE_WORD, "hello", relationships=relationships, examples=examples,
        )
        self.assertEqual(item["relationships"], relationships)
        self.assertEqual(item["examples"], examples)

    def test_source_context_is_preserved(self):
        store, _memory = _store()
        item = store.learn_item(
            "english", ITEM_TYPE_PHRASE, "how are you",
            source_context="asked during a greeting exchange",
        )
        self.assertEqual(item["source_context"], "asked during a greeting exchange")


class TestConfidenceIsStoredAndRetrieved(unittest.TestCase):
    """5 (+ 6 of prompt spec). Confidence is stored and retrieved."""

    def test_confidence_round_trips(self):
        store, _memory = _store()
        item = store.learn_item("english", ITEM_TYPE_WORD, "maybe", confidence=0.42)
        self.assertEqual(item["confidence"], 0.42)
        self.assertEqual(store.get_item("english", ITEM_TYPE_WORD, "maybe")["confidence"], 0.42)

    def test_new_item_without_confidence_defaults_to_1(self):
        store, _memory = _store()
        item = store.learn_item("english", ITEM_TYPE_WORD, "definitely")
        self.assertEqual(item["confidence"], 1.0)

    def test_confidence_is_clamped_into_the_valid_range(self):
        store, _memory = _store()
        low = store.learn_item("english", ITEM_TYPE_WORD, "low_conf", confidence=-5)
        high = store.learn_item("english", ITEM_TYPE_WORD, "high_conf", confidence=5)
        self.assertEqual(low["confidence"], 0.0)
        self.assertEqual(high["confidence"], 1.0)

    def test_non_numeric_confidence_is_rejected(self):
        store, _memory = _store()
        with self.assertRaises(TypeError):
            store.learn_item("english", ITEM_TYPE_WORD, "oops", confidence="high")


class TestReLearningUpdatesRatherThanDuplicates(unittest.TestCase):
    """6. Re-learning the same item updates the existing record instead of
    creating an unnecessary duplicate."""

    def test_relearning_the_same_key_updates_the_existing_row(self):
        store, memory = _store()
        first = store.learn_item("english", ITEM_TYPE_WORD, "run", meaning={"gloss": "to move fast"})
        second = store.learn_item(
            "english", ITEM_TYPE_WORD, "run", meaning={"gloss": "to move fast on foot"},
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["meaning"], {"gloss": "to move fast on foot"})

        rows = memory.query("SELECT COUNT(*) AS c FROM language_learning_items")
        self.assertEqual(rows[0]["c"], 1)

    def test_relearning_with_none_leaves_previous_fields_untouched(self):
        store, _memory = _store()
        store.learn_item(
            "english", ITEM_TYPE_WORD, "quick", confidence=0.7, source="user",
            source_context="original context",
        )
        updated = store.learn_item("english", ITEM_TYPE_WORD, "quick", confidence=0.95)
        # confidence explicitly changed...
        self.assertEqual(updated["confidence"], 0.95)
        # ...but source/source_context, not restated, are preserved.
        self.assertEqual(updated["source"], "user")
        self.assertEqual(updated["source_context"], "original context")

    def test_relearning_is_insensitive_to_case_and_whitespace_of_the_key(self):
        store, memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "Sun")
        store.learn_item("english", ITEM_TYPE_WORD, "  sun  ")
        rows = memory.query("SELECT COUNT(*) AS c FROM language_learning_items")
        self.assertEqual(rows[0]["c"], 1)

    def test_different_item_types_for_the_same_key_do_not_collide(self):
        store, memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "well")
        store.learn_item("english", ITEM_TYPE_PHRASE, "well")
        rows = memory.query("SELECT COUNT(*) AS c FROM language_learning_items")
        self.assertEqual(rows[0]["c"], 2)


class TestDifferentLanguagesStoreIndependentEntries(unittest.TestCase):
    """7. Different languages can store independent entries."""

    def test_the_same_key_in_two_languages_is_two_separate_items(self):
        store, memory = _store()
        english_no = store.learn_item("english", ITEM_TYPE_WORD, "no", meaning={"gloss": "negation"})
        spanish_no = store.learn_item(
            "spanish", ITEM_TYPE_WORD, "no", meaning={"gloss": "not / no (Spanish)"}
        )
        self.assertNotEqual(english_no["id"], spanish_no["id"])
        self.assertEqual(store.get_item("english", ITEM_TYPE_WORD, "no")["meaning"],
                         {"gloss": "negation"})
        self.assertEqual(store.get_item("spanish", ITEM_TYPE_WORD, "no")["meaning"],
                         {"gloss": "not / no (Spanish)"})
        rows = memory.query("SELECT COUNT(*) AS c FROM language_learning_items")
        self.assertEqual(rows[0]["c"], 2)

    def test_items_for_language_only_returns_that_languages_items(self):
        store, _memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "hello")
        store.learn_item("english", ITEM_TYPE_WORD, "goodbye")
        store.learn_item("persian", ITEM_TYPE_WORD, "سلام")
        english_items = store.items_for_language("english")
        self.assertEqual({i["key"] for i in english_items}, {"hello", "goodbye"})
        self.assertEqual(len(store.items_for_language("persian")), 1)

    def test_languages_lists_every_distinct_language_recorded(self):
        store, _memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "hello")
        store.learn_item("persian", ITEM_TYPE_WORD, "سلام")
        store.learn_item("german", ITEM_TYPE_WORD, "hallo")
        self.assertEqual(store.languages(), ["english", "german", "persian"])

    def test_arabic_and_persian_are_learned_as_distinct_languages(self):
        # Reuses canonical_language()'s existing distinction - Arabic and
        # Persian are separate canonical languages even though they share
        # a script.
        store, _memory = _store()
        store.learn_item("arabic", ITEM_TYPE_WORD, "مرحبا")
        store.learn_item("persian", ITEM_TYPE_WORD, "سلام")
        self.assertEqual(store.languages(), ["arabic", "persian"])


class TestEpisodicHistoryIsReused(unittest.TestCase):
    """Reuses the existing learning_events table rather than a second one."""

    def test_learning_an_item_records_a_learning_event(self):
        store, memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "hello", source="user")
        events = memory.recent_learning_events()
        self.assertTrue(any(e["event_type"] == "language_item_learned" for e in events))

    def test_updating_an_item_records_a_distinct_event_type(self):
        store, memory = _store()
        store.learn_item("english", ITEM_TYPE_WORD, "hello")
        store.learn_item("english", ITEM_TYPE_WORD, "hello", confidence=0.5)
        events = memory.recent_learning_events()
        types = [e["event_type"] for e in events if "hello" in e["target"]]
        self.assertEqual(types, ["language_item_learned", "language_item_updated"])


class TestCoreIntegration(unittest.TestCase):
    """8. Existing language and learning tests remain compatible - Core
    exposes the foundation through a clean, additive integration point."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_has_a_language_learning_store(self):
        self.assertIsInstance(self.core.language_learning, LanguageLearningStore)

    def test_core_learn_and_get_language_item_round_trip(self):
        self.core.learn_language_item(
            "english", ITEM_TYPE_WORD, "book", meaning={"gloss": "a bound set of pages"},
            confidence=0.8,
        )
        retrieved = self.core.get_language_item("english", ITEM_TYPE_WORD, "book")
        self.assertEqual(retrieved["meaning"], {"gloss": "a bound set of pages"})
        self.assertEqual(retrieved["confidence"], 0.8)

    def test_core_get_language_item_returns_none_when_unlearned(self):
        self.assertIsNone(self.core.get_language_item("english", ITEM_TYPE_WORD, "nope"))

    def test_language_learning_does_not_affect_ordinary_conversation(self):
        # This foundation is a separate table/entry point - it must not
        # change any existing conversational behavior.
        reply = self.core.process_input("Hello there.")
        self.assertIsInstance(reply, str)
        self.core.learn_language_item("english", ITEM_TYPE_WORD, "there")
        reply2 = self.core.process_input("qwerty zzznoxyzzz unmapped concept")
        self.assertIn("I don't have enough information", reply2)

    def test_language_learning_is_independent_of_knowledge_and_concepts(self):
        # Learning a language item must not create a knowledge/concept
        # entry, and vice versa - this is a separate table.
        self.core.learn_language_item("english", ITEM_TYPE_WORD, "gravity")
        self.assertIsNone(self.core.knowledge.get("gravity"))

        self.core.learn_from_text("Gravity pulls objects together.", auto_commit=True)
        # the natural-language learning pipeline must not have touched
        # (or created a duplicate of) the separately-learned language item
        item = self.core.get_language_item("english", ITEM_TYPE_WORD, "gravity")
        self.assertIsNotNone(item)
        self.assertEqual(item["version"], 1)


if __name__ == "__main__":
    unittest.main()
