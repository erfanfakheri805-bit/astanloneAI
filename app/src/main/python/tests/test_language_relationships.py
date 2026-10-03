"""
Tests for Prompt 417 - Learned Language Relationships.

`LanguageRelationshipStore` (language_intelligence/language_relationships.py)
connects the learned language items from Prompt 416 - and, optionally, a
Knowledge System concept - through structured, persistent, reference-checked
relationships, backed by ONE more MemorySystem table (schema migration 6) and
reachable from Core via two thin passthrough methods
(relate_language_items / get_language_relationships).

Run directly:
    python -m unittest tests.test_language_relationships -v
"""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import (
    LanguageLearningStore, ITEM_TYPE_WORD, ITEM_TYPE_PHRASE, ITEM_TYPE_PATTERN,
)
from language_intelligence.language_relationships import (
    LanguageRelationshipStore, item_ref, concept_ref,
    RELATION_SYNONYM, RELATION_ANTONYM, RELATION_TRANSLATION, RELATION_RELATED_MEANING,
    RELATION_EXAMPLE_USAGE, RELATION_GRAMMATICAL, RELATION_WORD_TO_PHRASE,
    RELATION_PHRASE_TO_PATTERN, RELATION_CONCEPT_TO_EXPRESSION, SUGGESTED_RELATION_TYPES,
)
from core.core import Core


class _StoreTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + the three composed stores."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "memory.db")
        self._open()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _open(self):
        self.memory = MemorySystem(self.db_path)
        self.items = LanguageLearningStore(self.memory)
        self.knowledge = KnowledgeSystem(self.memory)
        self.rels = LanguageRelationshipStore(self.memory, self.items, self.knowledge)

    def _count(self):
        return self.memory.query_one(
            "SELECT COUNT(*) AS c FROM language_item_relationships"
        )["c"]


class TestRelatingTwoLearnedItems(_StoreTestCase):
    """1. Two learned language items can be related."""

    def test_two_words_can_be_related(self):
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        glad = self.items.learn_item("en", ITEM_TYPE_WORD, "glad")
        result = self.rels.relate(happy, glad, RELATION_SYNONYM)
        self.assertTrue(result["created"])
        self.assertEqual(result["relation_type"], RELATION_SYNONYM)
        self.assertEqual({result["from"]["key"], result["to"]["key"]}, {"happy", "glad"})
        self.assertEqual(self._count(), 1)

    def test_endpoints_can_be_given_as_item_refs_instead_of_item_dicts(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "big")
        self.items.learn_item("en", ITEM_TYPE_WORD, "small")
        result = self.rels.relate(
            item_ref("en", ITEM_TYPE_WORD, "big"), item_ref("en", ITEM_TYPE_WORD, "small"),
            RELATION_ANTONYM,
        )
        self.assertTrue(result["created"])

    def test_endpoint_matching_reuses_the_416_key_identity(self):
        # Same case/whitespace-insensitive identity get_item() already uses.
        self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning")
        self.items.learn_item("en", ITEM_TYPE_WORD, "morning")
        result = self.rels.relate(
            item_ref("english", ITEM_TYPE_WORD, "  Morning "),
            item_ref("EN", ITEM_TYPE_PHRASE, "GOOD   MORNING"), RELATION_WORD_TO_PHRASE,
        )
        self.assertEqual(result["from"]["key"], "morning")
        self.assertEqual(result["to"]["key"], "good morning")

    def test_all_suggested_relation_types_are_accepted(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        for index, relation_type in enumerate(SUGGESTED_RELATION_TYPES):
            b = self.items.learn_item("en", ITEM_TYPE_WORD, f"b{index}")
            result = self.rels.relate(a, b, relation_type)
            self.assertEqual(result["relation_type"], relation_type)
        self.assertEqual(self._count(), len(SUGGESTED_RELATION_TYPES))

    def test_relation_type_is_an_open_vocabulary(self):
        # Not a closed system: a future learning module's own labels work.
        a = self.items.learn_item("de", "affix", "ge-")
        b = self.items.learn_item("de", ITEM_TYPE_WORD, "gemacht")
        result = self.rels.relate(a, b, "participle_prefix_of")
        self.assertEqual(result["relation_type"], "participle_prefix_of")

    def test_missing_or_blank_relation_type_is_rejected(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        for bad in ("", "   ", None):
            with self.assertRaises(ValueError):
                self.rels.relate(a, b, bad)
        self.assertEqual(self._count(), 0)

    def test_relating_writes_a_learning_event(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, "related_meaning", source="user", source_context="taught by user")
        self.rels.relate(a, b, "related_meaning")
        types = [e["event_type"] for e in self.memory.recent_learning_events()
                 if e["event_type"].startswith("language_relationship")]
        self.assertEqual(types, ["language_relationship_learned", "language_relationship_updated"])


class TestRetrievalFromEitherSide(_StoreTestCase):
    """2. A relationship can be retrieved from either side when appropriate."""

    def test_directed_relationship_is_outgoing_from_source_and_incoming_to_target(self):
        word = self.items.learn_item("en", ITEM_TYPE_WORD, "morning")
        phrase = self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning")
        self.rels.relate(word, phrase, RELATION_WORD_TO_PHRASE)

        from_word = self.rels.relationships_for(word)
        self.assertEqual(len(from_word), 1)
        self.assertEqual(from_word[0]["direction"], "outgoing")
        self.assertEqual(from_word[0]["related"]["key"], "good morning")

        from_phrase = self.rels.relationships_for(phrase)
        self.assertEqual(len(from_phrase), 1)
        self.assertEqual(from_phrase[0]["direction"], "incoming")
        self.assertEqual(from_phrase[0]["related"]["key"], "morning")
        self.assertEqual(from_phrase[0]["id"], from_word[0]["id"])

    def test_symmetric_relationship_is_retrievable_from_both_sides(self):
        happy = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        glad = self.items.learn_item("en", ITEM_TYPE_WORD, "glad")
        self.rels.relate(happy, glad, RELATION_SYNONYM)
        for me, other in ((happy, "glad"), (glad, "happy")):
            found = self.rels.relationships_for(me)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["direction"], "both")
            self.assertEqual(found[0]["related"]["key"], other)

    def test_retrieval_accepts_a_ref_not_only_a_learned_item_dict(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, RELATION_SYNONYM)
        self.assertEqual(len(self.rels.relationships_for(item_ref("english", "word", " A "))), 1)

    def test_item_with_no_relationships_or_unknown_item_yields_empty_list(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "lonely")
        self.assertEqual(self.rels.relationships_for(a), [])
        self.assertEqual(self.rels.relationships_for(item_ref("en", "word", "never learned")), [])
        self.assertEqual(self.rels.relationships_for(concept_ref("No Such Concept")), [])

    def test_relation_type_filter(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "hot")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "warm")
        c = self.items.learn_item("en", ITEM_TYPE_WORD, "cold")
        self.rels.relate(a, b, RELATION_RELATED_MEANING)
        self.rels.relate(a, c, RELATION_ANTONYM)
        only_antonyms = self.rels.relationships_for(a, relation_type="ANTONYM")
        self.assertEqual([r["related"]["key"] for r in only_antonyms], ["cold"])
        self.assertEqual(len(self.rels.relationships_for(a)), 2)

    def test_directed_relations_in_both_directions_are_distinct_relationships(self):
        # A directed relation has a meaning per direction, so a->b and b->a
        # are genuinely different facts, not duplicates.
        cat = self.items.learn_item("en", ITEM_TYPE_WORD, "cat")
        cats = self.items.learn_item("en", ITEM_TYPE_WORD, "cats")
        self.rels.relate(cat, cats, "plural_form", symmetric=False)
        self.rels.relate(cats, cat, "plural_form", symmetric=False)
        self.assertEqual(self._count(), 2)


class TestRelationshipTypeAndMetadataArePreserved(_StoreTestCase):
    """3. Relationship type (and metadata) is preserved."""

    def test_type_is_returned_exactly_as_given(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, "Grammatical_Relation")
        found = self.rels.relationships_for(a)[0]
        self.assertEqual(found["relation_type"], "Grammatical_Relation")

    def test_each_type_stays_attached_to_its_own_relationship(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "run")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "ran")
        c = self.items.learn_item("en", ITEM_TYPE_PHRASE, "run away")
        self.rels.relate(a, b, RELATION_GRAMMATICAL)
        self.rels.relate(a, c, RELATION_WORD_TO_PHRASE)
        by_related = {r["related"]["key"]: r["relation_type"] for r in self.rels.relationships_for(a)}
        self.assertEqual(by_related, {"ran": RELATION_GRAMMATICAL, "run away": RELATION_WORD_TO_PHRASE})

    def test_metadata_and_provenance_round_trip(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("fa", ITEM_TYPE_WORD, "ب")
        self.rels.relate(
            a, b, RELATION_TRANSLATION, metadata={"register": "formal", "notes": ["x", "y"]},
            confidence=0.7, source="user", source_context="the user said so",
            learning_method="manual",
        )
        found = self.rels.relationships_for(a)[0]
        self.assertEqual(found["metadata"], {"register": "formal", "notes": ["x", "y"]})
        self.assertEqual(found["confidence"], 0.7)
        self.assertEqual(found["source"], "user")
        self.assertEqual(found["source_context"], "the user said so")
        self.assertEqual(found["learning_method"], "manual")
        self.assertEqual(found["version"], 1)

    def test_new_relationship_without_confidence_defaults_to_1_and_is_clamped(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        c = self.items.learn_item("en", ITEM_TYPE_WORD, "c")
        self.assertEqual(self.rels.relate(a, b, RELATION_SYNONYM)["confidence"], 1.0)
        self.assertEqual(self.rels.relate(a, c, RELATION_SYNONYM, confidence=7)["confidence"], 1.0)
        with self.assertRaises(TypeError):
            self.rels.relate(b, c, RELATION_SYNONYM, confidence="high")

    def test_non_json_metadata_is_rejected_before_anything_is_written(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        with self.assertRaises(TypeError):
            self.rels.relate(a, b, RELATION_SYNONYM, metadata={"bad": object()})
        self.assertEqual(self._count(), 0)


class TestDuplicatesAreNotCreated(_StoreTestCase):
    """4. Duplicate relationships are not unnecessarily created."""

    def setUp(self):
        super().setUp()
        self.a = self.items.learn_item("en", ITEM_TYPE_WORD, "happy")
        self.b = self.items.learn_item("en", ITEM_TYPE_WORD, "glad")

    def test_stating_the_same_relationship_twice_creates_one_row(self):
        first = self.rels.relate(self.a, self.b, RELATION_SYNONYM)
        second = self.rels.relate(self.a, self.b, RELATION_SYNONYM)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self._count(), 1)

    def test_symmetric_relationship_stated_from_the_other_side_is_not_duplicated(self):
        first = self.rels.relate(self.a, self.b, RELATION_SYNONYM)
        second = self.rels.relate(self.b, self.a, RELATION_SYNONYM)
        self.assertFalse(second["created"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self._count(), 1)

    def test_relation_type_case_and_spacing_do_not_create_a_second_row(self):
        self.rels.relate(self.a, self.b, "related meaning")
        again = self.rels.relate(self.a, self.b, "  Related   MEANING ", symmetric=False)
        self.assertFalse(again["created"])
        self.assertEqual(self._count(), 1)

    def test_a_different_type_between_the_same_items_is_a_different_relationship(self):
        self.rels.relate(self.a, self.b, RELATION_SYNONYM)
        self.rels.relate(self.a, self.b, RELATION_RELATED_MEANING)
        self.assertEqual(self._count(), 2)

    def test_restating_refreshes_metadata_and_preserves_the_original(self):
        first = self.rels.relate(
            self.a, self.b, RELATION_SYNONYM, metadata={"n": 1}, confidence=0.6,
            source="user", source_context="ctx", learning_method="manual",
        )
        # nothing new given -> everything stored is left alone
        untouched = self.rels.relate(self.a, self.b, RELATION_SYNONYM)
        self.assertEqual(untouched["metadata"], {"n": 1})
        self.assertEqual(untouched["confidence"], 0.6)
        self.assertEqual(untouched["source"], "user")
        self.assertEqual(untouched["source_context"], "ctx")
        self.assertEqual(untouched["learning_method"], "manual")
        self.assertEqual(untouched["version"], 2)
        self.assertEqual(untouched["created_at"], first["created_at"])
        # something new given -> replaces just that
        changed = self.rels.relate(self.a, self.b, RELATION_SYNONYM, metadata={"n": 2}, confidence=0.9)
        self.assertEqual(changed["metadata"], {"n": 2})
        self.assertEqual(changed["confidence"], 0.9)
        self.assertEqual(changed["source"], "user")
        self.assertEqual(changed["version"], 3)
        self.assertEqual(changed["created_at"], first["created_at"])
        self.assertEqual(self._count(), 1)

    def test_restating_with_the_opposite_symmetry_is_refused_not_duplicated(self):
        self.rels.relate(self.a, self.b, RELATION_SYNONYM)  # symmetric by default
        with self.assertRaises(ValueError):
            self.rels.relate(self.a, self.b, RELATION_SYNONYM, symmetric=False)
        with self.assertRaises(ValueError):
            self.rels.relate(self.b, self.a, RELATION_SYNONYM, symmetric=False)
        self.assertEqual(self._count(), 1)

    def test_the_database_itself_refuses_a_duplicate_row(self):
        # Belt and braces: even bypassing the store, the unique index holds.
        self.rels.relate(self.a, self.b, RELATION_SYNONYM)
        row = self.memory.query_one("SELECT * FROM language_item_relationships")
        with self.assertRaises(sqlite3.IntegrityError):
            self.memory._run(
                "INSERT INTO language_item_relationships (from_item_id, to_item_id, relation_type, "
                "normalized_type, created_at, updated_at) VALUES (?, ?, 'x', ?, 'n', 'n')",
                (row["from_item_id"], row["to_item_id"], row["normalized_type"]),
            )


class TestLanguageAndLocaleStayCorrect(_StoreTestCase):
    """5. Language/locale information remains correct."""

    def setUp(self):
        super().setUp()
        self.hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        self.hi = self.items.learn_item("en", ITEM_TYPE_WORD, "hi")
        self.salam = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")
        self.bonjour = self.items.learn_item("fr", ITEM_TYPE_WORD, "bonjour")
        self.rels.relate(self.hello, self.hi, RELATION_SYNONYM)
        self.rels.relate(self.hello, self.salam, RELATION_TRANSLATION)
        self.rels.relate(self.hello, self.bonjour, RELATION_TRANSLATION)

    def test_each_endpoint_carries_its_own_canonical_language(self):
        found = {r["related"]["key"]: r["related"]["language"]
                 for r in self.rels.relationships_for(self.hello)}
        self.assertEqual(found, {"hi": "english", "سلام": "persian", "bonjour": "french"})

    def test_a_cross_language_relationship_keeps_both_languages(self):
        found = self.rels.relationships_for(self.salam)[0]
        self.assertEqual(found["related"]["language"], "english")
        self.assertEqual({found["from"]["language"], found["to"]["language"]}, {"english", "persian"})

    def test_filtering_by_language_keeps_only_that_related_language(self):
        persian = self.rels.relationships_for(self.hello, language="fa")
        self.assertEqual([r["related"]["key"] for r in persian], ["سلام"])
        english = self.rels.relationships_for(self.hello, language="en")
        self.assertEqual([r["related"]["key"] for r in english], ["hi"])
        self.assertEqual(self.rels.relationships_for(self.hello, language="german"), [])

    def test_language_filter_uses_the_same_aliases_as_the_rest_of_the_package(self):
        by_code = self.rels.relationships_for(self.hello, language="fa")
        by_name = self.rels.relationships_for(self.hello, language="Persian")
        by_locale = self.rels.relationships_for(self.hello, language="fa-IR")
        self.assertEqual([r["id"] for r in by_code], [r["id"] for r in by_name])
        self.assertEqual([r["id"] for r in by_code], [r["id"] for r in by_locale])

    def test_language_and_relation_type_filters_combine(self):
        found = self.rels.relationships_for(self.hello, relation_type=RELATION_TRANSLATION, language="fr")
        self.assertEqual([r["related"]["key"] for r in found], ["bonjour"])

    def test_relationships_in_language_lists_every_relationship_with_an_end_there(self):
        persian = self.rels.relationships_in_language("persian")
        self.assertEqual(len(persian), 1)
        self.assertEqual(persian[0]["relation_type"], RELATION_TRANSLATION)
        english = self.rels.relationships_in_language("en")
        self.assertEqual(len(english), 3)  # the synonym, plus both translations' English end
        self.assertEqual(len(self.rels.relationships_in_language("en", relation_type="synonym")), 1)
        self.assertEqual(self.rels.relationships_in_language("german"), [])

    def test_a_blank_or_placeholder_language_filter_is_rejected(self):
        with self.assertRaises(ValueError):
            self.rels.relationships_for(self.hello, language="unknown")
        with self.assertRaises(ValueError):
            self.rels.relationships_in_language("")

    def test_the_same_key_in_two_languages_relates_independently(self):
        # "pain" is a word in both English and French - different items.
        en_pain = self.items.learn_item("en", ITEM_TYPE_WORD, "pain")
        fr_pain = self.items.learn_item("fr", ITEM_TYPE_WORD, "pain")
        bread = self.items.learn_item("en", ITEM_TYPE_WORD, "bread")
        self.rels.relate(fr_pain, bread, RELATION_TRANSLATION)
        self.assertEqual(self.rels.relationships_for(en_pain), [])
        self.assertEqual(len(self.rels.relationships_for(fr_pain)), 1)

    def test_language_is_not_assumed_to_be_a_known_language(self):
        # Language-agnostic by construction, like Prompt 416.
        a = self.items.learn_item("tlh", ITEM_TYPE_WORD, "nuqneH")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "what do you want")
        result = self.rels.relate(a, b, RELATION_TRANSLATION)
        self.assertEqual({result["from"]["language"], result["to"]["language"]}, {"english", "tlh"})


class TestPhraseAndExpressionRelationships(_StoreTestCase):
    """6. Phrase/expression relationships are supported, not only words."""

    def test_word_to_phrase(self):
        word = self.items.learn_item("en", ITEM_TYPE_WORD, "morning")
        phrase = self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning")
        result = self.rels.relate(word, phrase, RELATION_WORD_TO_PHRASE)
        self.assertEqual((result["from"]["item_type"], result["to"]["item_type"]), ("word", "phrase"))

    def test_phrase_to_sentence_pattern(self):
        phrase = self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning")
        pattern = self.items.learn_item("en", ITEM_TYPE_PATTERN, "good ___")
        result = self.rels.relate(phrase, pattern, RELATION_PHRASE_TO_PATTERN)
        self.assertEqual((result["from"]["item_type"], result["to"]["item_type"]), ("phrase", "pattern"))

    def test_phrase_to_meaning(self):
        # A "meaning" is just another learned item_type - nothing here
        # assumes a relationship is word -> word.
        phrase = self.items.learn_item("en", ITEM_TYPE_PHRASE, "break a leg")
        meaning = self.items.learn_item("en", "meaning", "good luck")
        self.rels.relate(phrase, meaning, "expresses")
        found = self.rels.relationships_for(phrase)[0]
        self.assertEqual(found["related"]["item_type"], "meaning")
        self.assertEqual(found["direction"], "outgoing")

    def test_phrase_to_phrase_across_languages(self):
        en = self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning")
        fa = self.items.learn_item("fa", ITEM_TYPE_PHRASE, "صبح بخیر")
        result = self.rels.relate(en, fa, RELATION_TRANSLATION)
        self.assertEqual({result["from"]["item_type"], result["to"]["item_type"]}, {"phrase"})
        self.assertEqual(len(self.rels.relationships_for(fa, language="en")), 1)

    def test_example_usage_links_an_item_to_an_example_sentence_item(self):
        word = self.items.learn_item("en", ITEM_TYPE_WORD, "borrow")
        example = self.items.learn_item("en", "example", "May I borrow your pen?")
        self.rels.relate(word, example, RELATION_EXAMPLE_USAGE)
        self.assertEqual(self.rels.relationships_for(example)[0]["direction"], "incoming")

    def test_concept_to_expression_and_expression_to_concept(self):
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        phrase = self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning")
        forward = self.rels.relate(concept_ref("Greeting"), phrase, RELATION_CONCEPT_TO_EXPRESSION)
        self.assertEqual(forward["from"], {"kind": "concept", "concept": "Greeting", "language": None})
        self.assertEqual(forward["to"]["item_type"], "phrase")

        from_phrase = self.rels.relationships_for(phrase)[0]
        self.assertEqual(from_phrase["direction"], "incoming")
        self.assertEqual(from_phrase["related"]["concept"], "Greeting")
        from_concept = self.rels.relationships_for(concept_ref("Greeting"))[0]
        self.assertEqual(from_concept["direction"], "outgoing")
        self.assertEqual(from_concept["related"]["key"], "good morning")

        # ... and the reverse direction (expression -> concept) is a valid endpoint pair too
        backward = self.rels.relate(phrase, concept_ref("Greeting"), "expresses_concept")
        self.assertTrue(backward["created"])
        self.assertEqual(backward["to"]["concept"], "Greeting")

    def test_a_concept_is_linked_to_expressions_in_several_languages(self):
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        en = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        fa = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")
        self.rels.relate(concept_ref("Greeting"), en, RELATION_CONCEPT_TO_EXPRESSION)
        self.rels.relate(concept_ref("Greeting"), fa, RELATION_CONCEPT_TO_EXPRESSION)
        persian_only = self.rels.relationships_for(concept_ref("Greeting"), language="persian")
        self.assertEqual([r["related"]["key"] for r in persian_only], ["سلام"])

    def test_a_concept_never_matches_a_language_filter(self):
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        en = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        self.rels.relate(concept_ref("Greeting"), en, RELATION_CONCEPT_TO_EXPRESSION)
        self.assertEqual(self.rels.relationships_for(en, language="en"), [])


class TestNoDanglingReferences(_StoreTestCase):
    """A relationship must refer to actual learned items."""

    def test_unlearned_endpoint_is_rejected_and_nothing_is_created(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        items_before = self.memory.counts()["language_learning_item_count"]
        knowledge_before = self.memory.counts()["knowledge_count"]
        for args in (
            (a, item_ref("en", ITEM_TYPE_WORD, "ghost")),
            (item_ref("en", ITEM_TYPE_WORD, "ghost"), a),
            (a, item_ref("en", ITEM_TYPE_PHRASE, "a")),      # right key, wrong item_type
            (a, item_ref("fa", ITEM_TYPE_WORD, "a")),        # right key, wrong language
            (a, concept_ref("Ghost Concept")),
        ):
            with self.assertRaises(ValueError):
                self.rels.relate(*args, RELATION_SYNONYM)
        self.assertEqual(self._count(), 0)
        # nothing was auto-created on either side
        self.assertEqual(self.memory.counts()["language_learning_item_count"], items_before)
        self.assertEqual(self.memory.counts()["knowledge_count"], knowledge_before)

    def test_a_knowledge_entry_that_is_not_a_concept_is_not_a_valid_endpoint(self):
        self.knowledge.learn("Some Skill", "not a concept", kind="skill")
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        with self.assertRaises(ValueError):
            self.rels.relate(concept_ref("Some Skill"), a, RELATION_CONCEPT_TO_EXPRESSION)

    def test_an_item_cannot_be_related_to_itself(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        with self.assertRaises(ValueError):
            self.rels.relate(a, item_ref("EN", ITEM_TYPE_WORD, " A "), RELATION_SYNONYM)
        self.assertEqual(self._count(), 0)

    def test_malformed_endpoints_are_rejected(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        with self.assertRaises(TypeError):
            self.rels.relate(a, "b", RELATION_SYNONYM)
        with self.assertRaises(ValueError):
            self.rels.relate(a, {"key": "b"}, RELATION_SYNONYM)  # no language / item_type

    def test_the_database_refuses_a_dangling_reference_even_if_the_store_is_bypassed(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        with self.assertRaises(sqlite3.IntegrityError):  # foreign key on to_item_id
            self.memory._run(
                "INSERT INTO language_item_relationships (from_item_id, to_item_id, relation_type, "
                "normalized_type, created_at, updated_at) VALUES (?, 99999, 'x', 'x', 'n', 'n')",
                (a["id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):  # foreign key on to_concept
            self.memory._run(
                "INSERT INTO language_item_relationships (from_item_id, to_concept, relation_type, "
                "normalized_type, created_at, updated_at) VALUES (?, 'No Such Concept', 'x', 'x', 'n', 'n')",
                (a["id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):  # an end with neither item nor concept
            self.memory._run(
                "INSERT INTO language_item_relationships (from_item_id, relation_type, "
                "normalized_type, created_at, updated_at) VALUES (?, 'x', 'x', 'n', 'n')",
                (a["id"],),
            )
        self.assertEqual(self._count(), 0)

    def test_relating_does_not_touch_the_knowledge_relationship_graph(self):
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        self.rels.relate(concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION)
        self.assertEqual(self.knowledge.relationships_for("Greeting"), {"outgoing": [], "incoming": []})
        self.assertEqual(self.memory.query("SELECT * FROM relationships"), [])
        self.assertEqual(self.memory.counts()["knowledge_count"], 1)


class TestDeterminism(_StoreTestCase):
    """Relationships are deterministic."""

    def _build(self, order):
        hub = self.items.learn_item("en", ITEM_TYPE_WORD, "hub")
        targets = {name: self.items.learn_item("en", ITEM_TYPE_WORD, name) for name in ("delta", "alpha", "charlie", "bravo")}
        for name in order:
            self.rels.relate(hub, targets[name], RELATION_RELATED_MEANING)
        self.rels.relate(hub, targets["alpha"], RELATION_ANTONYM)
        return [(r["relation_type"], r["related"]["key"]) for r in self.rels.relationships_for(hub)]

    def test_result_order_does_not_depend_on_insertion_order(self):
        first = self._build(["delta", "alpha", "charlie", "bravo"])
        self.assertEqual(first, [
            ("antonym", "alpha"), ("related_meaning", "alpha"), ("related_meaning", "bravo"),
            ("related_meaning", "charlie"), ("related_meaning", "delta"),
        ])
        self._tmpdir.cleanup()
        self.setUp()
        second = self._build(["bravo", "charlie", "alpha", "delta"])
        self.assertEqual(first, second)

    def test_repeated_reads_return_identical_results(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, RELATION_SYNONYM, metadata={"k": "v"})
        self.assertEqual(self.rels.relationships_for(a), self.rels.relationships_for(a))

    def test_symmetric_relationship_is_stored_in_one_canonical_order(self):
        # The persisted representation must not depend on which side the
        # caller happened to state first.
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        stated_backwards = self.rels.relate(b, a, RELATION_SYNONYM)
        self.assertEqual((stated_backwards["from"]["key"], stated_backwards["to"]["key"]), ("a", "b"))
        again = self.rels.relate(a, b, RELATION_SYNONYM)
        self.assertEqual((again["from"]["key"], again["to"]["key"]), ("a", "b"))

        # and a second database that states it forwards stores the same shape
        other_dir = tempfile.TemporaryDirectory()
        self.addCleanup(other_dir.cleanup)
        memory = MemorySystem(os.path.join(other_dir.name, "other.db"))
        items = LanguageLearningStore(memory)
        rels = LanguageRelationshipStore(memory, items)
        x = items.learn_item("en", ITEM_TYPE_WORD, "a")
        y = items.learn_item("en", ITEM_TYPE_WORD, "b")
        forwards = rels.relate(x, y, RELATION_SYNONYM)
        self.assertEqual((forwards["from"]["key"], forwards["to"]["key"]), ("a", "b"))

    def test_relearning_an_item_keeps_its_relationships(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, RELATION_SYNONYM)
        again = self.items.learn_item("en", ITEM_TYPE_WORD, "A", meaning={"gloss": "first letter"})
        self.assertEqual(again["id"], a["id"])
        self.assertEqual(len(self.rels.relationships_for(again)), 1)


class TestRelationshipsPersist(_StoreTestCase):
    """7. Relationships persist across reload/reinitialization."""

    def test_relationships_survive_a_reopened_memory_system(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        salam = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        self.rels.relate(
            hello, salam, RELATION_TRANSLATION, metadata={"note": "informal"}, confidence=0.8,
            source="user", source_context="taught", learning_method="manual",
        )
        self.rels.relate(concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION)
        before = self.rels.relationships_for(hello)

        self._open()  # brand-new MemorySystem / stores on the same file

        after = self.rels.relationships_for(item_ref("en", ITEM_TYPE_WORD, "hello"))
        self.assertEqual(after, before)
        translation = [r for r in after if r["relation_type"] == RELATION_TRANSLATION][0]
        self.assertEqual(translation["related"]["language"], "persian")
        self.assertEqual(translation["metadata"], {"note": "informal"})
        self.assertEqual(translation["confidence"], 0.8)
        self.assertTrue(translation["symmetric"])
        self.assertEqual(len(self.rels.relationships_for(concept_ref("Greeting"))), 1)
        self.assertEqual(len(self.rels.relationships_in_language("fa")), 1)

    def test_a_duplicate_is_still_not_created_after_reload(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, RELATION_SYNONYM)
        self._open()
        again = self.rels.relate(item_ref("en", "word", "b"), item_ref("en", "word", "a"), RELATION_SYNONYM)
        self.assertFalse(again["created"])
        self.assertEqual(again["version"], 2)
        self.assertEqual(self._count(), 1)

    def test_a_database_from_before_this_stage_upgrades_and_keeps_its_data(self):
        # Simulate a schema-5 database (Prompt 416): items exist, the
        # relationships table does not.
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning={"gloss": "letter"})
        raw = sqlite3.connect(self.db_path)
        raw.execute("DROP TABLE language_item_relationships")
        raw.execute("UPDATE config SET value = '5' WHERE key = 'schema_version'")
        raw.commit()
        raw.close()

        self._open()  # runs the pending migration

        self.assertEqual(self.memory.get_config("schema_version"), 6)
        self.assertEqual(self.items.get_item("en", ITEM_TYPE_WORD, "a")["meaning"], {"gloss": "letter"})
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.assertTrue(self.rels.relate(a, b, RELATION_SYNONYM)["created"])


class TestCoreIntegrationAndPrompt416Compatibility(unittest.TestCase):
    """8. Existing Prompt 416 learning tests remain compatible - Core
    exposes relationships through a clean, additive integration point."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        self.skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=self.db_path, skill_definitions_dir=self.skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_owns_a_relationship_store_that_shares_its_other_systems(self):
        store = self.core.language_relationships
        self.assertIsInstance(store, LanguageRelationshipStore)
        self.assertIs(store.memory, self.core.memory)
        self.assertIs(store.language_learning, self.core.language_learning)
        self.assertIs(store.knowledge, self.core.knowledge)

    def test_core_relate_and_get_round_trip(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello")
        salam = self.core.learn_language_item("fa", ITEM_TYPE_WORD, "سلام")
        result = self.core.relate_language_items(hello, salam, RELATION_TRANSLATION, confidence=0.9)
        self.assertTrue(result["created"])
        found = self.core.get_language_relationships(hello)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["relation_type"], RELATION_TRANSLATION)
        self.assertEqual(found[0]["related"]["language"], "persian")
        self.assertEqual(len(self.core.get_language_relationships(hello, language="fa")), 1)
        self.assertEqual(self.core.get_language_relationships(hello, language="fr"), [])

    def test_core_relates_a_concept_taught_through_the_concept_system(self):
        self.core.concepts.define("Greeting", "A polite acknowledgement")
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello")
        result = self.core.relate_language_items(
            concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION
        )
        self.assertTrue(result["created"])
        # the Concept System's own view of "Greeting" is unchanged
        self.assertEqual(
            self.core.concepts.get_with_relations("Greeting")["relationships"],
            {"outgoing": [], "incoming": []},
        )

    def test_core_rejects_a_dangling_endpoint(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello")
        with self.assertRaises(ValueError):
            self.core.relate_language_items(hello, item_ref("fa", ITEM_TYPE_WORD, "سلام"), RELATION_TRANSLATION)

    def test_relationships_do_not_change_the_416_item_records(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "greeting"})
        hi = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hi")
        self.core.relate_language_items(hello, hi, RELATION_SYNONYM)
        after = self.core.get_language_item("en", ITEM_TYPE_WORD, "hello")
        self.assertEqual(after["version"], 1)
        self.assertEqual(after["meaning"], {"gloss": "greeting"})
        self.assertEqual(after["relationships"], [])  # the 416 free-form blob is untouched
        self.assertEqual(after, hello)

    def test_relationships_do_not_affect_ordinary_conversation(self):
        a = self.core.learn_language_item("en", ITEM_TYPE_WORD, "there")
        b = self.core.learn_language_item("en", ITEM_TYPE_WORD, "here")
        self.core.relate_language_items(a, b, RELATION_ANTONYM)
        self.assertIsInstance(self.core.process_input("Hello there."), str)
        self.assertIn("I don't have enough information",
                      self.core.process_input("qwerty zzznoxyzzz unmapped concept"))

    def test_core_relationships_persist_across_a_new_core_on_the_same_database(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello")
        salam = self.core.learn_language_item("fa", ITEM_TYPE_WORD, "سلام")
        self.core.relate_language_items(hello, salam, RELATION_TRANSLATION, metadata={"k": 1})
        second = Core(memory_db_path=self.db_path, skill_definitions_dir=self.skills_dir)
        found = second.get_language_relationships(item_ref("en", ITEM_TYPE_WORD, "hello"))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["metadata"], {"k": 1})
        self.assertEqual(found[0]["related"]["key"], "سلام")


if __name__ == "__main__":
    unittest.main()
