"""
Tests for Prompt 418 - Learned Meaning Resolution.

`MeaningResolver` (language_intelligence/meaning_resolution.py) reports what
the system has LEARNED an expression to mean, using only the language items
(Prompt 416) and relationships (Prompt 417) already stored, plus the
Knowledge System's concepts. It is a deterministic, bounded, read-only
lookup - not a language model and not an NLU engine - and is reachable from
Core via one thin passthrough (resolve_language_meaning).

Run directly:
    python -m unittest tests.test_meaning_resolution -v
"""

import json
import os
import random
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
    LanguageRelationshipStore, concept_ref,
    RELATION_SYNONYM, RELATION_ANTONYM, RELATION_TRANSLATION, RELATION_RELATED_MEANING,
    RELATION_PHRASE_TO_PATTERN, RELATION_CONCEPT_TO_EXPRESSION,
)
from language_intelligence.meaning_resolution import (
    MeaningResolver, MeaningResolutionResult, STATUS_RESOLVED, STATUS_NOT_FOUND, ALL_STATUSES,
    REASON_UNKNOWN_EXPRESSION, REASON_NO_LEARNED_MEANING,
    DEFAULT_MAX_DEPTH, MAX_DEPTH_LIMIT, DEFAULT_MAX_RELATED, MAX_RELATED_LIMIT, MAX_MATCHED_ITEMS,
)
from core.core import Core


class _ResolverTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + the composed stores and resolver."""

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
        self.resolver = MeaningResolver(self.items, self.rels, self.knowledge)

    def _related_summary(self, meaning_entry):
        """(relation_type, key-or-concept, depth) for each related entry."""
        return [
            (e["relation_type"], e["related"].get("key") or e["related"].get("concept"), e["depth"])
            for e in meaning_entry["related"]
        ]

    def _count_relationship_reads(self):
        calls = []
        # always wrap the pristine method, so repeated calls never stack wrappers
        original = LanguageRelationshipStore.relationships_for.__get__(self.rels)

        def counting(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        self.rels.relationships_for = counting
        return calls


class TestKnownWordResolvesItsStoredMeaning(_ResolverTestCase):
    """1. A known learned word resolves its stored meaning."""

    def test_a_learned_word_resolves_its_meaning_and_context(self):
        self.items.learn_item(
            "en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"},
            examples=["Hello, how are you?"], confidence=0.9, source="user",
            source_context="the user taught it", learning_method="manual",
        )
        result = self.resolver.resolve("hello", "en")
        self.assertIsInstance(result, MeaningResolutionResult)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertTrue(result.resolved)
        self.assertIsNone(result.reason)
        self.assertEqual(len(result.meanings), 1)
        entry = result.meanings[0]
        self.assertEqual(entry["meaning"], {"gloss": "a greeting"})
        self.assertEqual(entry["examples"], ["Hello, how are you?"])
        self.assertEqual(entry["confidence"], 0.9)
        self.assertEqual(entry["source"], "user")
        self.assertEqual(entry["source_context"], "the user taught it")
        self.assertEqual(entry["learning_method"], "manual")
        self.assertTrue(entry["has_stored_meaning"])
        self.assertEqual((entry["language"], entry["item_type"], entry["key"]), ("english", "word", "hello"))
        self.assertFalse(result.ambiguous)

    def test_the_meaning_is_returned_uninterpreted(self):
        shape = {"senses": [{"pos": "noun", "gloss": "x"}], "roles": ["agent"], "n": 3}
        self.items.learn_item("en", ITEM_TYPE_WORD, "thing", meaning=shape)
        self.assertEqual(self.resolver.resolve("thing", "en").meanings[0]["meaning"], shape)

    def test_expression_matching_reuses_the_416_key_identity(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning="greeting")
        for spelling in ("HELLO", "  hello ", "Hello"):
            self.assertEqual(self.resolver.resolve(spelling, "english").status, STATUS_RESOLVED)

    def test_the_result_echoes_the_expression_as_asked(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning="greeting")
        result = self.resolver.resolve("HELLO", "en")
        self.assertEqual(result.expression, "HELLO")
        self.assertEqual(result.language, "english")

    def test_the_result_is_json_serializable(self):
        self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام", meaning={"gloss": "hello"})
        payload = json.dumps(self.resolver.resolve("سلام", "fa").to_dict(), ensure_ascii=False)
        self.assertIn("سلام", payload)

    def test_to_dict_returns_a_copy(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "greeting"})
        result = self.resolver.resolve("hello", "en")
        result.to_dict()["meanings"][0]["meaning"]["gloss"] = "tampered"
        self.assertEqual(result.meanings[0]["meaning"], {"gloss": "greeting"})

    def test_resolving_reflects_a_re_learned_meaning(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "bank", meaning={"gloss": "old"})
        self.items.learn_item("en", ITEM_TYPE_WORD, "bank", meaning={"gloss": "new"})
        self.assertEqual(self.resolver.resolve("bank", "en").meanings[0]["meaning"], {"gloss": "new"})


class TestKnownPhraseResolvesItsStoredMeaning(_ResolverTestCase):
    """2. A known phrase resolves its stored meaning."""

    def test_a_phrase_resolves_its_meaning(self):
        self.items.learn_item(
            "en", ITEM_TYPE_PHRASE, "break a leg", meaning={"gloss": "good luck"},
            examples=["Break a leg tonight!"],
        )
        result = self.resolver.resolve("break a leg", "en")
        self.assertEqual(result.status, STATUS_RESOLVED)
        entry = result.meanings[0]
        self.assertEqual(entry["item_type"], ITEM_TYPE_PHRASE)
        self.assertEqual(entry["meaning"], {"gloss": "good luck"})
        self.assertEqual(entry["examples"], ["Break a leg tonight!"])

    def test_phrase_spacing_and_case_do_not_matter(self):
        self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning", meaning={"gloss": "greeting"})
        self.assertEqual(self.resolver.resolve("  GOOD    Morning ", "en").status, STATUS_RESOLVED)

    def test_a_sentence_pattern_resolves_too(self):
        self.items.learn_item("en", ITEM_TYPE_PATTERN, "___ is a ___", meaning={"role": "classification"})
        entry = self.resolver.resolve("___ is a ___", "en").meanings[0]
        self.assertEqual(entry["item_type"], ITEM_TYPE_PATTERN)
        self.assertEqual(entry["meaning"], {"role": "classification"})

    def test_a_word_and_a_phrase_with_the_same_key_are_told_apart_by_item_type(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "thank you", meaning={"gloss": "as a noun"})
        self.items.learn_item("en", ITEM_TYPE_PHRASE, "thank you", meaning={"gloss": "gratitude"})
        only_phrase = self.resolver.resolve("thank you", "en", item_type=ITEM_TYPE_PHRASE)
        self.assertEqual([m["meaning"] for m in only_phrase.meanings], [{"gloss": "gratitude"}])
        self.assertEqual(only_phrase.item_type, ITEM_TYPE_PHRASE)

    def test_a_custom_item_type_resolves(self):
        self.items.learn_item("de", "idiom", "Tomaten auf den Augen haben", meaning={"gloss": "not seeing the obvious"})
        result = self.resolver.resolve("Tomaten auf den Augen haben", "de")
        self.assertEqual(result.meanings[0]["item_type"], "idiom")


class TestRelationshipsProvideAdditionalMeaning(_ResolverTestCase):
    """3. A relationship can provide additional meaning information."""

    def test_a_translation_provides_the_meaning_of_an_item_with_none_of_its_own(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"})
        salam = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")  # nothing stored about it
        self.rels.relate(hello, salam, RELATION_TRANSLATION)

        result = self.resolver.resolve("سلام", "fa")
        self.assertEqual(result.status, STATUS_RESOLVED)
        entry = result.meanings[0]
        self.assertFalse(entry["has_stored_meaning"])
        self.assertEqual(len(entry["related"]), 1)
        related = entry["related"][0]
        self.assertEqual(related["relation_type"], RELATION_TRANSLATION)
        self.assertEqual(related["direction"], "both")
        self.assertEqual(related["depth"], 1)
        self.assertEqual(related["related"]["language"], "english")
        self.assertEqual(related["related"]["key"], "hello")
        self.assertEqual(related["related"]["meaning"], {"gloss": "a greeting"})

    def test_a_relationship_adds_to_an_items_own_meaning_without_replacing_it(self):
        hot = self.items.learn_item("en", ITEM_TYPE_WORD, "hot", meaning={"gloss": "high temperature"})
        warm = self.items.learn_item("en", ITEM_TYPE_WORD, "warm", meaning={"gloss": "moderately hot"})
        self.rels.relate(hot, warm, RELATION_RELATED_MEANING)
        entry = self.resolver.resolve("hot", "en").meanings[0]
        self.assertEqual(entry["meaning"], {"gloss": "high temperature"})
        self.assertEqual(entry["related"][0]["related"]["meaning"], {"gloss": "moderately hot"})

    def test_expression_to_concept_provides_the_concepts_description(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        self.knowledge.learn("Greeting", "A polite acknowledgement of someone's arrival", kind="concept")
        self.rels.relate(concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION)

        entry = self.resolver.resolve("hello", "en").meanings[0]
        self.assertEqual(len(entry["related"]), 1)
        related = entry["related"][0]
        self.assertEqual(related["relation_type"], RELATION_CONCEPT_TO_EXPRESSION)
        self.assertEqual(related["direction"], "incoming")  # stored concept -> expression
        self.assertEqual(related["related"]["kind"], "concept")
        self.assertEqual(related["related"]["concept"], "Greeting")
        self.assertEqual(related["related"]["description"], "A polite acknowledgement of someone's arrival")
        self.assertEqual(related["related"]["status"], "active")
        self.assertIsNone(related["related"]["language"])

    def test_a_concept_reached_from_the_expression_side_direction_is_outgoing(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        self.rels.relate(hello, concept_ref("Greeting"), "expresses_concept")
        related = self.resolver.resolve("hello", "en").meanings[0]["related"][0]
        self.assertEqual(related["direction"], "outgoing")
        self.assertEqual(related["related"]["concept"], "Greeting")

    def test_a_stub_concept_is_reported_as_it_is_not_dressed_up(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello")
        self.knowledge.learn("Greeting", None, kind="concept", status="stub")
        self.rels.relate(concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION)
        related = self.resolver.resolve("hello", "en").meanings[0]["related"][0]["related"]
        self.assertIsNone(related["description"])
        self.assertEqual(related["status"], "stub")

    def test_relationship_confidence_and_metadata_are_passed_through(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        b = self.items.learn_item("fa", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, RELATION_TRANSLATION, metadata={"register": "formal"}, confidence=0.6)
        related = self.resolver.resolve("a", "en").meanings[0]["related"][0]
        self.assertEqual(related["confidence"], 0.6)
        self.assertEqual(related["metadata"], {"register": "formal"})

    def test_via_identifies_the_item_the_relationship_was_followed_from(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, RELATION_SYNONYM)
        related = self.resolver.resolve("a", "en").meanings[0]["related"][0]
        self.assertEqual((related["via"]["kind"], related["via"]["key"]), ("item", "a"))
        self.assertEqual(related["via"]["id"], a["id"])

    def test_phrase_to_pattern_relationship_is_followed(self):
        phrase = self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning", meaning={"gloss": "greeting"})
        pattern = self.items.learn_item("en", ITEM_TYPE_PATTERN, "good ___", meaning={"role": "greeting frame"})
        self.rels.relate(phrase, pattern, RELATION_PHRASE_TO_PATTERN)
        related = self.resolver.resolve("good morning", "en").meanings[0]["related"][0]
        self.assertEqual(related["related"]["item_type"], ITEM_TYPE_PATTERN)
        self.assertEqual(related["related"]["meaning"], {"role": "greeting frame"})

    def test_several_relationships_are_all_reported_in_a_deterministic_order(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning="greeting")
        hi = self.items.learn_item("en", ITEM_TYPE_WORD, "hi")
        salam = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        self.rels.relate(hello, salam, RELATION_TRANSLATION)
        self.rels.relate(hello, hi, RELATION_SYNONYM)
        self.rels.relate(concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION)
        entry = self.resolver.resolve("hello", "en").meanings[0]
        self.assertEqual(self._related_summary(entry), [
            (RELATION_CONCEPT_TO_EXPRESSION, "Greeting", 1),
            (RELATION_SYNONYM, "hi", 1),
            (RELATION_TRANSLATION, "سلام", 1),
        ])

    def test_relation_types_restricts_which_relationships_are_followed(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning="greeting")
        hi = self.items.learn_item("en", ITEM_TYPE_WORD, "hi")
        salam = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")
        self.rels.relate(hello, salam, RELATION_TRANSLATION)
        self.rels.relate(hello, hi, RELATION_SYNONYM)
        only = self.resolver.resolve("hello", "en", relation_types=[" TRANSLATION "]).meanings[0]
        self.assertEqual(self._related_summary(only), [(RELATION_TRANSLATION, "سلام", 1)])
        as_string = self.resolver.resolve("hello", "en", relation_types="synonym").meanings[0]
        self.assertEqual(self._related_summary(as_string), [(RELATION_SYNONYM, "hi", 1)])

    def test_an_empty_relation_types_follows_nothing_but_keeps_the_stored_meaning(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning="greeting")
        hi = self.items.learn_item("en", ITEM_TYPE_WORD, "hi")
        self.rels.relate(hello, hi, RELATION_SYNONYM)
        entry = self.resolver.resolve("hello", "en", relation_types=[]).meanings[0]
        self.assertEqual(entry["related"], [])
        self.assertEqual(entry["meaning"], "greeting")
        # ... and an item with nothing stored of its own then has nothing learned
        self.rels.relate(hi, self.items.learn_item("en", ITEM_TYPE_WORD, "hiya"), RELATION_SYNONYM)
        nothing = self.resolver.resolve("hiya", "en", relation_types=[])
        self.assertEqual(nothing.status, STATUS_NOT_FOUND)


class TestLanguageAndLocaleAreRespected(_ResolverTestCase):
    """4. Language/locale is respected - an identical string is not one
    global meaning."""

    def setUp(self):
        super().setUp()
        self.en_pain = self.items.learn_item("en", ITEM_TYPE_WORD, "pain", meaning={"gloss": "physical suffering"})
        self.fr_pain = self.items.learn_item("fr", ITEM_TYPE_WORD, "pain", meaning={"gloss": "bread"})
        self.bread = self.items.learn_item("en", ITEM_TYPE_WORD, "bread", meaning={"gloss": "baked food"})
        self.ache = self.items.learn_item("en", ITEM_TYPE_WORD, "ache", meaning={"gloss": "dull pain"})
        self.rels.relate(self.fr_pain, self.bread, RELATION_TRANSLATION)
        self.rels.relate(self.en_pain, self.ache, RELATION_SYNONYM)

    def test_each_language_resolves_to_its_own_meaning(self):
        english = self.resolver.resolve("pain", "en")
        french = self.resolver.resolve("pain", "fr")
        self.assertEqual([m["meaning"] for m in english.meanings], [{"gloss": "physical suffering"}])
        self.assertEqual([m["meaning"] for m in french.meanings], [{"gloss": "bread"}])
        self.assertEqual(english.language, "english")
        self.assertEqual(french.language, "french")

    def test_relationships_do_not_leak_between_languages(self):
        english = self.resolver.resolve("pain", "en").meanings[0]
        french = self.resolver.resolve("pain", "fr").meanings[0]
        self.assertEqual([r["related"]["key"] for r in english["related"]], ["ache"])
        self.assertEqual([r["related"]["key"] for r in french["related"]], ["bread"])

    def test_language_aliases_and_locales_resolve_the_same_entry(self):
        by_code = self.resolver.resolve("pain", "fr")
        by_name = self.resolver.resolve("pain", "French")
        self.assertEqual(by_code.meanings, by_name.meanings)
        self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام", meaning={"gloss": "hello"})
        for spelling in ("fa", "persian", "fa-IR"):
            self.assertEqual(self.resolver.resolve("سلام", spelling).status, STATUS_RESOLVED)

    def test_an_expression_learned_only_in_another_language_is_not_found(self):
        result = self.resolver.resolve("pain", "de")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_UNKNOWN_EXPRESSION)
        self.assertEqual(self.resolver.resolve("bread", "fr").status, STATUS_NOT_FOUND)

    def test_without_a_language_every_languages_meaning_is_returned_separately(self):
        result = self.resolver.resolve("pain")
        self.assertIsNone(result.language)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual([(m["language"], m["meaning"]["gloss"]) for m in result.meanings],
                         [("english", "physical suffering"), ("french", "bread")])
        self.assertTrue(result.ambiguous)
        # never merged: each keeps its own relationships
        self.assertEqual([r["related"]["key"] for r in result.meanings[0]["related"]], ["ache"])
        self.assertEqual([r["related"]["key"] for r in result.meanings[1]["related"]], ["bread"])

    def test_the_same_script_in_two_languages_stays_two_meanings(self):
        self.items.learn_item("fa", ITEM_TYPE_WORD, "كتاب", meaning={"gloss": "book (Persian)"})
        self.items.learn_item("ar", ITEM_TYPE_WORD, "كتاب", meaning={"gloss": "book (Arabic)"})
        result = self.resolver.resolve("كتاب")
        self.assertEqual([(m["language"], m["meaning"]["gloss"]) for m in result.meanings],
                         [("arabic", "book (Arabic)"), ("persian", "book (Persian)")])
        self.assertEqual(len(self.resolver.resolve("كتاب", "ar").meanings), 1)

    def test_a_language_that_is_not_a_known_language_still_works(self):
        self.items.learn_item("tlh", ITEM_TYPE_WORD, "nuqneH", meaning={"gloss": "greeting"})
        self.assertEqual(self.resolver.resolve("nuqneH", "tlh").status, STATUS_RESOLVED)

    def test_a_placeholder_language_is_rejected(self):
        for bad in ("unknown", ""):
            with self.assertRaises(ValueError):
                self.resolver.resolve("pain", bad)


class TestUnknownExpressionsAreNotFound(_ResolverTestCase):
    """5. Unknown expressions return NOT_FOUND."""

    def test_the_two_statuses_have_the_required_values(self):
        self.assertEqual(STATUS_RESOLVED, "RESOLVED")
        self.assertEqual(STATUS_NOT_FOUND, "NOT_FOUND")
        self.assertEqual(set(ALL_STATUSES), {"RESOLVED", "NOT_FOUND"})

    def test_an_unknown_expression_is_not_found(self):
        result = self.resolver.resolve("qwertyzz", "en")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertFalse(result.resolved)
        self.assertEqual(result.reason, REASON_UNKNOWN_EXPRESSION)
        self.assertEqual(result.meanings, [])
        self.assertEqual(result.matched_items, [])
        self.assertFalse(result.ambiguous)
        self.assertFalse(result.truncated)

    def test_an_empty_store_is_not_found_with_and_without_a_language(self):
        self.assertEqual(self.resolver.resolve("anything").status, STATUS_NOT_FOUND)
        self.assertEqual(self.resolver.resolve("anything", "fa").status, STATUS_NOT_FOUND)

    def test_a_known_item_with_no_learned_meaning_is_not_found_but_says_so(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "blank")
        result = self.resolver.resolve("blank", "en")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_NO_LEARNED_MEANING)
        self.assertEqual(result.meanings, [])
        self.assertEqual([(i["language"], i["key"]) for i in result.matched_items], [("english", "blank")])

    def test_blank_stored_meanings_count_as_no_meaning(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="   ")
        self.items.learn_item("en", ITEM_TYPE_WORD, "b", meaning=[])
        self.items.learn_item("en", ITEM_TYPE_WORD, "c", meaning={})
        for key in "abc":
            self.assertEqual(self.resolver.resolve(key, "en").reason, REASON_NO_LEARNED_MEANING)

    def test_falsy_but_real_stored_values_are_a_meaning(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "zero", meaning=0)
        self.assertEqual(self.resolver.resolve("zero", "en").status, STATUS_RESOLVED)

    def test_no_meaning_is_never_invented_from_a_lookalike(self):
        # No fuzzy matching, stemming or guessing: only the same key resolves.
        self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning="greeting")
        for other in ("hell", "helloo", "hello world", "hallo"):
            self.assertEqual(self.resolver.resolve(other, "en").status, STATUS_NOT_FOUND)

    def test_a_relationship_alone_does_not_make_an_unrelated_expression_resolve(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b", meaning="y")
        self.items.learn_item("en", ITEM_TYPE_WORD, "c")
        self.rels.relate(a, b, RELATION_SYNONYM)
        self.assertEqual(self.resolver.resolve("c", "en").status, STATUS_NOT_FOUND)

    def test_malformed_arguments_are_errors_not_not_found(self):
        for bad in ("", "   ", None):
            with self.assertRaises(ValueError):
                self.resolver.resolve(bad, "en")
        with self.assertRaises(ValueError):
            self.resolver.resolve("a", "en", item_type=" ")
        with self.assertRaises(ValueError):
            self.resolver.resolve("a", "en", max_depth=-1)
        with self.assertRaises(ValueError):
            self.resolver.resolve("a", "en", max_related=-1)
        for bad in ("2", 1.5, True):
            with self.assertRaises(TypeError):
                self.resolver.resolve("a", "en", max_depth=bad)
            with self.assertRaises(TypeError):
                self.resolver.resolve("a", "en", max_related=bad)
        with self.assertRaises(ValueError):
            self.resolver.resolve("a", "en", relation_types=[""])


class TestBoundedRelationshipTraversal(_ResolverTestCase):
    """6. Bounded relationship traversal works without excessive
    traversal."""

    def _chain(self, length, prefix="c"):
        nodes = [self.items.learn_item("en", ITEM_TYPE_WORD, f"{prefix}{i}",
                                       meaning={"gloss": f"g{i}"}) for i in range(length)]
        for left, right in zip(nodes, nodes[1:]):
            self.rels.relate(left, right, RELATION_RELATED_MEANING)
        return nodes

    def test_the_default_follows_direct_relationships_only(self):
        self._chain(5)
        self.assertEqual(DEFAULT_MAX_DEPTH, 1)
        entry = self.resolver.resolve("c0", "en").meanings[0]
        self.assertEqual(self._related_summary(entry), [(RELATION_RELATED_MEANING, "c1", 1)])

    def test_max_depth_extends_the_walk_one_hop_at_a_time(self):
        self._chain(6)
        two = self.resolver.resolve("c0", "en", max_depth=2).meanings[0]
        self.assertEqual([(k, d) for _t, k, d in self._related_summary(two)], [("c1", 1), ("c2", 2)])
        three = self.resolver.resolve("c0", "en", max_depth=3).meanings[0]
        self.assertEqual([(k, d) for _t, k, d in self._related_summary(three)], [("c1", 1), ("c2", 2), ("c3", 3)])

    def test_a_deeper_hop_records_the_node_it_was_reached_through(self):
        self._chain(4)
        entry = self.resolver.resolve("c0", "en", max_depth=2).meanings[0]
        second_hop = entry["related"][1]
        self.assertEqual(second_hop["related"]["key"], "c2")
        self.assertEqual(second_hop["via"]["key"], "c1")

    def test_depth_above_the_hard_cap_is_clamped_and_reported(self):
        self._chain(8)
        result = self.resolver.resolve("c0", "en", max_depth=10_000)
        self.assertEqual(result.limits["max_depth"], MAX_DEPTH_LIMIT)
        keys = [k for _t, k, _d in self._related_summary(result.meanings[0])]
        self.assertEqual(keys, ["c1", "c2", "c3"])  # never reaches c4
        self.assertFalse(result.truncated)  # stopping at max_depth is scope, not truncation

    def test_depth_zero_follows_no_relationships(self):
        self._chain(3)
        result = self.resolver.resolve("c0", "en", max_depth=0)
        self.assertEqual(result.status, STATUS_RESOLVED)  # its own stored meaning
        self.assertEqual(result.meanings[0]["related"], [])
        self.assertFalse(result.meanings[0]["related_truncated"])

    def test_a_walk_from_the_middle_goes_both_ways_and_never_echoes_the_start(self):
        self._chain(5)
        entry = self.resolver.resolve("c2", "en", max_depth=2).meanings[0]
        found = [(k, d) for _t, k, d in self._related_summary(entry)]
        self.assertEqual(sorted(found), [("c0", 2), ("c1", 1), ("c3", 1), ("c4", 2)])
        self.assertNotIn("c2", [k for k, _d in found])

    def test_a_cycle_terminates_and_never_repeats_a_relationship(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        c = self.items.learn_item("en", ITEM_TYPE_WORD, "c")
        # a directed ring a -> b -> c -> a, followed to the deepest allowed hop
        for source, target in ((a, b), (b, c), (c, a)):
            self.rels.relate(source, target, "leads_to", symmetric=False)
        calls = self._count_relationship_reads()
        entry = self.resolver.resolve("a", "en", max_depth=MAX_DEPTH_LIMIT).meanings[0]
        keys = [k for _t, k, _d in self._related_summary(entry)]
        self.assertNotIn("a", keys)               # the start is never echoed back
        self.assertLessEqual(len(entry["related"]), 3)  # three relationships exist in total
        self.assertLessEqual(len(calls), len(entry["related"]) + 1)

    def test_a_self_referencing_web_of_symmetric_links_terminates(self):
        nodes = [self.items.learn_item("en", ITEM_TYPE_WORD, f"n{i}", meaning="m") for i in range(6)]
        for i, left in enumerate(nodes):
            for right in nodes[i + 1:]:
                self.rels.relate(left, right, RELATION_RELATED_MEANING)  # fully connected
        entry = self.resolver.resolve("n0", "en", max_depth=MAX_DEPTH_LIMIT).meanings[0]
        keys = [k for _t, k, _d in self._related_summary(entry)]
        self.assertEqual(sorted(keys), ["n1", "n2", "n3", "n4", "n5"])  # each once, never n0
        self.assertTrue(all(d == 1 for _t, _k, d in self._related_summary(entry)))

    def test_every_direct_relationship_is_reported_even_to_the_same_target(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        b = self.items.learn_item("fa", ITEM_TYPE_WORD, "b", meaning="y")
        self.rels.relate(a, b, RELATION_TRANSLATION)
        self.rels.relate(a, b, RELATION_RELATED_MEANING)
        entry = self.resolver.resolve("a", "en").meanings[0]
        self.assertEqual(self._related_summary(entry),
                         [(RELATION_RELATED_MEANING, "b", 1), (RELATION_TRANSLATION, "b", 1)])

    def test_a_node_reached_by_two_direct_relationships_is_expanded_only_once(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        c = self.items.learn_item("en", ITEM_TYPE_WORD, "c")
        self.rels.relate(a, b, RELATION_TRANSLATION)
        self.rels.relate(a, b, RELATION_RELATED_MEANING)  # b is reported twice at depth 1 ...
        self.rels.relate(b, c, RELATION_SYNONYM)
        calls = self._count_relationship_reads()
        entry = self.resolver.resolve("a", "en", max_depth=2).meanings[0]
        self.assertEqual([k for _t, k, _d in self._related_summary(entry)], ["b", "b", "c"])
        self.assertEqual(len(calls), 2)  # ... yet read once for a and once for b, not once per report

    def test_beyond_the_first_hop_a_node_is_reported_once_at_its_shortest_distance(self):
        # a - b, a - c, b - c : c is a direct relationship of a (depth 1),
        # so reaching it again through b must not add a second entry.
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        c = self.items.learn_item("en", ITEM_TYPE_WORD, "c")
        d = self.items.learn_item("en", ITEM_TYPE_WORD, "d")
        for left, right in ((a, b), (a, c), (b, c), (b, d), (c, d)):
            self.rels.relate(left, right, RELATION_RELATED_MEANING)
        entry = self.resolver.resolve("a", "en", max_depth=3).meanings[0]
        self.assertEqual(self._related_summary(entry), [
            (RELATION_RELATED_MEANING, "b", 1), (RELATION_RELATED_MEANING, "c", 1),
            (RELATION_RELATED_MEANING, "d", 2),
        ])
        self.assertEqual(entry["related"][2]["via"]["key"], "b")  # first in deterministic order

    def test_invariants_hold_on_many_random_graphs(self):
        # Seeded, so deterministic: directed and symmetric links of several
        # types over a small node set, resolved from every node at every
        # depth and several budgets.
        rng = random.Random(418)
        nodes = [self.items.learn_item("en", ITEM_TYPE_WORD, f"w{i}", meaning=f"m{i}") for i in range(9)]
        types = [(RELATION_SYNONYM, None), (RELATION_TRANSLATION, None),
                 ("leads_to", False), ("linked_to", True)]
        for _ in range(40):
            left, right = rng.sample(nodes, 2)
            relation_type, symmetric = rng.choice(types)
            try:
                self.rels.relate(left, right, relation_type, symmetric=symmetric)
            except ValueError:
                pass  # e.g. the same pair restated with the opposite symmetry
        deep_entries_seen = truncated_seen = 0
        for node in nodes:
            for depth in range(0, MAX_DEPTH_LIMIT + 1):
                for budget in (1, 4, 10):
                    calls = self._count_relationship_reads()
                    result = self.resolver.resolve(node["key"], "en", max_depth=depth, max_related=budget)
                    related = result.meanings[0]["related"]
                    label = f"{node['key']} depth={depth} budget={budget}"
                    self.assertLessEqual(len(related), budget, label)
                    self.assertLessEqual(len(calls), budget + 1, label)
                    self.assertTrue(all(1 <= e["depth"] <= depth for e in related), label)
                    self.assertNotIn(node["id"], [e["related"]["id"] for e in related], label)
                    self.assertEqual(depth == 0, related == [], label)
                    facts = [(e["via"]["id"], e["relation_type"], e["direction"], e["related"]["id"])
                             for e in related]
                    self.assertEqual(len(facts), len(set(facts)), label)  # no relationship reported twice
                    deeper = [e["related"]["id"] for e in related if e["depth"] > 1]
                    self.assertEqual(len(deeper), len(set(deeper)), label)  # beyond hop 1: once per node
                    direct = {e["related"]["id"] for e in related if e["depth"] == 1}
                    self.assertFalse(direct & set(deeper), label)  # ... and never repeating a direct one
                    deep_entries_seen += len(deeper)
                    truncated_seen += result.truncated
        # guard against passing vacuously on graphs too sparse to matter
        self.assertGreater(deep_entries_seen, 0)
        self.assertGreater(truncated_seen, 0)

    def test_a_hub_is_cut_off_at_max_related_and_reported_as_truncated(self):
        hub = self.items.learn_item("en", ITEM_TYPE_WORD, "hub", meaning="center")
        for i in range(200):
            self.rels.relate(hub, self.items.learn_item("en", ITEM_TYPE_WORD, f"n{i:03d}"), RELATION_RELATED_MEANING)
        calls = self._count_relationship_reads()
        result = self.resolver.resolve("hub", "en", max_depth=2)
        entry = result.meanings[0]
        self.assertEqual(len(entry["related"]), DEFAULT_MAX_RELATED)
        self.assertTrue(entry["related_truncated"])
        self.assertTrue(result.truncated)
        # the first ten in the deterministic order, not an arbitrary ten
        self.assertEqual([k for _t, k, _d in self._related_summary(entry)],
                         [f"n{i:03d}" for i in range(10)])
        # work is bounded by max_related, never by the 200 neighbours
        self.assertLessEqual(len(calls), DEFAULT_MAX_RELATED + 1)

    def test_max_related_is_clamped_to_the_hard_cap_and_reported(self):
        hub = self.items.learn_item("en", ITEM_TYPE_WORD, "hub", meaning="center")
        for i in range(MAX_RELATED_LIMIT + 30):
            self.rels.relate(hub, self.items.learn_item("en", ITEM_TYPE_WORD, f"n{i:03d}"), RELATION_RELATED_MEANING)
        result = self.resolver.resolve("hub", "en", max_related=1_000_000)
        self.assertEqual(result.limits["max_related"], MAX_RELATED_LIMIT)
        self.assertEqual(len(result.meanings[0]["related"]), MAX_RELATED_LIMIT)
        self.assertTrue(result.truncated)

    def test_a_smaller_max_related_is_honoured(self):
        hub = self.items.learn_item("en", ITEM_TYPE_WORD, "hub", meaning="center")
        for i in range(8):
            self.rels.relate(hub, self.items.learn_item("en", ITEM_TYPE_WORD, f"n{i}"), RELATION_RELATED_MEANING)
        result = self.resolver.resolve("hub", "en", max_related=3)
        self.assertEqual(len(result.meanings[0]["related"]), 3)
        self.assertTrue(result.truncated)
        # exactly at the bound is not truncation
        exact = self.resolver.resolve("hub", "en", max_related=8)
        self.assertEqual(len(exact.meanings[0]["related"]), 8)
        self.assertFalse(exact.truncated)

    def test_max_related_zero_still_reports_that_relationships_exist(self):
        a = self.items.learn_item("en", ITEM_TYPE_WORD, "a")
        b = self.items.learn_item("en", ITEM_TYPE_WORD, "b")
        self.rels.relate(a, b, RELATION_SYNONYM)
        result = self.resolver.resolve("a", "en", max_related=0)
        self.assertEqual(result.status, STATUS_RESOLVED)  # not silently "no meaning"
        self.assertEqual(result.meanings[0]["related"], [])
        self.assertTrue(result.meanings[0]["related_truncated"])

    def test_expansions_are_bounded_even_when_each_neighbour_is_itself_a_hub(self):
        hub = self.items.learn_item("en", ITEM_TYPE_WORD, "hub", meaning="center")
        for i in range(4):
            spoke = self.items.learn_item("en", ITEM_TYPE_WORD, f"s{i}")
            self.rels.relate(hub, spoke, RELATION_RELATED_MEANING)
            for j in range(100):
                self.rels.relate(spoke, self.items.learn_item("en", ITEM_TYPE_WORD, f"s{i}x{j:03d}"), RELATION_RELATED_MEANING)
        calls = self._count_relationship_reads()
        result = self.resolver.resolve("hub", "en", max_depth=MAX_DEPTH_LIMIT, max_related=10)
        self.assertEqual(len(result.meanings[0]["related"]), 10)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(calls), 10 + 1)  # nowhere near the ~400 reachable nodes

    def test_the_number_of_matched_items_is_bounded(self):
        for i in range(MAX_MATCHED_ITEMS + 5):
            self.items.learn_item("en", f"type{i:02d}", "run", meaning={"n": i})
        result = self.resolver.resolve("run", "en")
        self.assertEqual(len(result.meanings), MAX_MATCHED_ITEMS)
        self.assertTrue(result.truncated)
        self.assertEqual(result.limits["max_matched_items"], MAX_MATCHED_ITEMS)
        # ... and the ones kept are the first in the deterministic order
        self.assertEqual([m["item_type"] for m in result.meanings],
                         [f"type{i:02d}" for i in range(MAX_MATCHED_ITEMS)])

    def test_exactly_at_the_matched_items_bound_is_not_truncated(self):
        for i in range(MAX_MATCHED_ITEMS):
            self.items.learn_item("en", f"type{i:02d}", "run", meaning={"n": i})
        result = self.resolver.resolve("run", "en")
        self.assertEqual(len(result.meanings), MAX_MATCHED_ITEMS)
        self.assertFalse(result.truncated)

    def test_the_traversal_result_does_not_depend_on_insertion_order(self):
        def build(order):
            hub = self.items.learn_item("en", ITEM_TYPE_WORD, "hub", meaning="center")
            nodes = {n: self.items.learn_item("en", ITEM_TYPE_WORD, n, meaning=n) for n in ("delta", "alpha", "charlie", "bravo")}
            for n in order:
                self.rels.relate(hub, nodes[n], RELATION_RELATED_MEANING)
            self.rels.relate(hub, nodes["alpha"], RELATION_ANTONYM)
            return self._related_summary(self.resolver.resolve("hub", "en", max_depth=2).meanings[0])

        first = build(["delta", "alpha", "charlie", "bravo"])
        self._tmpdir.cleanup()
        self.setUp()
        second = build(["bravo", "charlie", "alpha", "delta"])
        self.assertEqual(first, second)
        self.assertEqual(first[0], (RELATION_ANTONYM, "alpha", 1))

    def test_repeated_resolution_is_identical(self):
        self._chain(4)
        one = self.resolver.resolve("c0", "en", max_depth=3).to_dict()
        two = self.resolver.resolve("c0", "en", max_depth=3).to_dict()
        self.assertEqual(one, two)


class TestMultipleMeaningsStayDistinguishable(_ResolverTestCase):
    """7. Multiple meanings can remain distinguishable when the existing
    data supports them."""

    def test_the_same_word_under_two_item_types_gives_two_separate_meanings(self):
        noun = self.items.learn_item("en", "noun", "run", meaning={"gloss": "an act of running"})
        verb = self.items.learn_item("en", "verb", "run", meaning={"gloss": "to move quickly on foot"})
        jog = self.items.learn_item("fa", ITEM_TYPE_WORD, "دویدن")
        self.rels.relate(verb, jog, RELATION_TRANSLATION)

        result = self.resolver.resolve("run", "en")
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertTrue(result.ambiguous)
        self.assertEqual([(m["item_type"], m["meaning"]["gloss"]) for m in result.meanings],
                         [("noun", "an act of running"), ("verb", "to move quickly on foot")])
        # each meaning carries only ITS relationships
        self.assertEqual(result.meanings[0]["related"], [])
        self.assertEqual([r["related"]["key"] for r in result.meanings[1]["related"]], ["دویدن"])
        self.assertEqual(len(result.matched_items), 2)

    def test_the_item_type_filter_selects_one_meaning(self):
        self.items.learn_item("en", "noun", "run", meaning={"gloss": "noun sense"})
        self.items.learn_item("en", "verb", "run", meaning={"gloss": "verb sense"})
        only = self.resolver.resolve("run", "en", item_type="verb")
        self.assertFalse(only.ambiguous)
        self.assertEqual(only.meanings[0]["meaning"], {"gloss": "verb sense"})

    def test_one_item_linked_to_several_concepts_keeps_each_concept_separate(self):
        bank = self.items.learn_item("en", ITEM_TYPE_WORD, "bank")
        self.knowledge.learn("Financial Institution", "Holds and lends money", kind="concept")
        self.knowledge.learn("River Edge", "The land alongside a river", kind="concept")
        self.rels.relate(concept_ref("Financial Institution"), bank, RELATION_CONCEPT_TO_EXPRESSION)
        self.rels.relate(concept_ref("River Edge"), bank, RELATION_CONCEPT_TO_EXPRESSION)
        related = self.resolver.resolve("bank", "en").meanings[0]["related"]
        self.assertEqual({r["related"]["concept"]: r["related"]["description"] for r in related},
                         {"Financial Institution": "Holds and lends money",
                          "River Edge": "The land alongside a river"})

    def test_a_word_and_a_phrase_with_the_same_text_are_separate_entries(self):
        self.items.learn_item("en", ITEM_TYPE_WORD, "good morning", meaning={"gloss": "as a word"})
        self.items.learn_item("en", ITEM_TYPE_PHRASE, "good morning", meaning={"gloss": "a greeting"})
        result = self.resolver.resolve("good morning", "en")
        self.assertEqual([(m["item_type"], m["meaning"]["gloss"]) for m in result.meanings],
                         [("phrase", "a greeting"), ("word", "as a word")])

    def test_only_the_meaning_bearing_matches_are_listed_but_all_matches_are_reported(self):
        self.items.learn_item("en", "noun", "run", meaning={"gloss": "noun sense"})
        self.items.learn_item("en", "verb", "run")  # known, nothing learned
        result = self.resolver.resolve("run", "en")
        self.assertEqual([m["item_type"] for m in result.meanings], ["noun"])
        self.assertFalse(result.ambiguous)
        self.assertEqual([i["item_type"] for i in result.matched_items], ["noun", "verb"])

    def test_meanings_are_ordered_not_ranked_by_confidence(self):
        self.items.learn_item("en", "b_sense", "x", meaning="second", confidence=0.99)
        self.items.learn_item("en", "a_sense", "x", meaning="first", confidence=0.10)
        self.assertEqual([m["meaning"] for m in self.resolver.resolve("x", "en").meanings], ["first", "second"])


class TestResolutionIsReadOnly(_ResolverTestCase):
    """Resolution never writes: not an item, a relationship, a knowledge
    entry, or a learning event."""

    def test_resolving_changes_nothing(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "greeting"})
        salam = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        self.rels.relate(hello, salam, RELATION_TRANSLATION)
        self.rels.relate(concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION)

        def snapshot():
            return (
                self.memory.counts(),
                self.memory.query("SELECT * FROM language_learning_items ORDER BY id"),
                self.memory.query("SELECT * FROM language_item_relationships ORDER BY id"),
                self.memory.query("SELECT * FROM knowledge ORDER BY id"),
                self.memory.query("SELECT * FROM relationships ORDER BY id"),
                self.memory.recent_learning_events(limit=1000),
            )

        before = snapshot()
        for expression, language in (("hello", "en"), ("سلام", "fa"), ("nothing", "en"), ("hello", None)):
            self.resolver.resolve(expression, language, max_depth=3)
        self.assertEqual(snapshot(), before)

    def test_unknown_expressions_and_concepts_are_never_created(self):
        self.resolver.resolve("ghost", "en")
        self.assertEqual(self.memory.counts()["language_learning_item_count"], 0)
        self.assertEqual(self.memory.counts()["knowledge_count"], 0)


class TestFindItems(_ResolverTestCase):
    """The one read-only addition to the Prompt 416 store."""

    def test_finds_every_item_sharing_a_written_form_in_a_deterministic_order(self):
        self.items.learn_item("fr", ITEM_TYPE_WORD, "pain")
        self.items.learn_item("en", ITEM_TYPE_WORD, "pain")
        self.items.learn_item("en", ITEM_TYPE_PHRASE, "Pain")
        found = self.items.find_items("  PAIN ")
        self.assertEqual([(i["language"], i["item_type"]) for i in found],
                         [("english", "phrase"), ("english", "word"), ("french", "word")])

    def test_language_and_item_type_narrow_the_match(self):
        self.items.learn_item("fr", ITEM_TYPE_WORD, "pain")
        self.items.learn_item("en", ITEM_TYPE_WORD, "pain")
        self.assertEqual([i["language"] for i in self.items.find_items("pain", language="fa")], [])
        self.assertEqual([i["language"] for i in self.items.find_items("pain", language="fr")], ["french"])
        self.assertEqual(self.items.find_items("pain", language="en", item_type=ITEM_TYPE_PHRASE), [])

    def test_limit_caps_the_rows_read(self):
        for i in range(5):
            self.items.learn_item("en", f"t{i}", "x")
        self.assertEqual(len(self.items.find_items("x", limit=2)), 2)
        self.assertEqual(self.items.find_items("x", limit=0), [])
        with self.assertRaises(ValueError):
            self.items.find_items("x", limit=-1)
        with self.assertRaises(TypeError):
            self.items.find_items("x", limit="2")

    def test_it_agrees_with_get_item_and_is_read_only(self):
        item = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "g"})
        self.assertEqual(self.items.find_items("hello", language="en"), [item])
        self.assertEqual(self.items.get_item("en", ITEM_TYPE_WORD, "hello"), item)
        self.assertEqual(self.items.get_item("en", ITEM_TYPE_WORD, "hello")["version"], 1)
        with self.assertRaises(ValueError):
            self.items.find_items("")
        with self.assertRaises(ValueError):
            self.items.find_items("hello", language="unknown")


class TestPersistenceAcrossReload(_ResolverTestCase):
    """Resolution reads only persisted data - reopening changes nothing."""

    def test_resolution_gives_the_same_answer_after_reopening_the_database(self):
        hello = self.items.learn_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "greeting"})
        salam = self.items.learn_item("fa", ITEM_TYPE_WORD, "سلام")
        self.knowledge.learn("Greeting", "A polite acknowledgement", kind="concept")
        self.rels.relate(hello, salam, RELATION_TRANSLATION)
        self.rels.relate(concept_ref("Greeting"), salam, RELATION_CONCEPT_TO_EXPRESSION)
        before = self.resolver.resolve("سلام", "fa").to_dict()

        self._open()  # brand-new MemorySystem / stores / resolver on the same file

        self.assertEqual(self.resolver.resolve("سلام", "fa").to_dict(), before)


class TestCoreIntegrationAndPrompt416417Compatibility(unittest.TestCase):
    """8. Existing Prompt 416 and 417 behaviour remains compatible - Core
    exposes resolution through one additive integration point."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        self.skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=self.db_path, skill_definitions_dir=self.skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_owns_a_resolver_that_shares_its_other_systems(self):
        resolver = self.core.meaning_resolver
        self.assertIsInstance(resolver, MeaningResolver)
        self.assertIs(resolver.language_learning, self.core.language_learning)
        self.assertIs(resolver.relationships, self.core.language_relationships)
        self.assertIs(resolver.knowledge, self.core.knowledge)

    def test_core_resolves_through_the_416_and_417_entry_points(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "a greeting"})
        salam = self.core.learn_language_item("fa", ITEM_TYPE_WORD, "سلام")
        self.core.relate_language_items(hello, salam, RELATION_TRANSLATION)

        result = self.core.resolve_language_meaning("سلام", "fa")
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.meanings[0]["related"][0]["related"]["meaning"], {"gloss": "a greeting"})
        self.assertEqual(self.core.resolve_language_meaning("hello", language="en", max_depth=0)
                         .meanings[0]["related"], [])
        self.assertEqual(self.core.resolve_language_meaning("nope", "en").status, STATUS_NOT_FOUND)

    def test_core_resolves_a_concept_taught_through_the_concept_system(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello")
        self.core.concepts.define("Greeting", "A polite acknowledgement")
        self.core.relate_language_items(concept_ref("Greeting"), hello, RELATION_CONCEPT_TO_EXPRESSION)
        related = self.core.resolve_language_meaning("hello", "en").meanings[0]["related"][0]
        self.assertEqual(related["related"]["description"], "A polite acknowledgement")

    def test_core_resolution_survives_a_new_core_on_the_same_database(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "greeting"})
        salam = self.core.learn_language_item("fa", ITEM_TYPE_WORD, "سلام")
        self.core.relate_language_items(hello, salam, RELATION_TRANSLATION)
        expected = self.core.resolve_language_meaning("سلام", "fa").to_dict()
        second = Core(memory_db_path=self.db_path, skill_definitions_dir=self.skills_dir)
        self.assertEqual(second.resolve_language_meaning("سلام", "fa").to_dict(), expected)

    def test_resolution_does_not_change_the_416_or_417_records(self):
        hello = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hello", meaning={"gloss": "greeting"})
        hi = self.core.learn_language_item("en", ITEM_TYPE_WORD, "hi")
        relationship = self.core.relate_language_items(hello, hi, RELATION_SYNONYM)
        self.core.resolve_language_meaning("hello", "en", max_depth=3)
        self.assertEqual(self.core.get_language_item("en", ITEM_TYPE_WORD, "hello"), hello)
        self.assertEqual(self.core.get_language_relationships(hello)[0]["version"], relationship["version"])

    def test_resolution_does_not_affect_ordinary_conversation(self):
        self.core.learn_language_item("en", ITEM_TYPE_WORD, "there", meaning={"gloss": "in that place"})
        self.core.resolve_language_meaning("there", "en")
        self.assertIsInstance(self.core.process_input("Hello there."), str)
        self.assertIn("I don't have enough information",
                      self.core.process_input("qwerty zzznoxyzzz unmapped concept"))

    def test_learning_and_relating_still_behave_exactly_as_before(self):
        # 416: re-learning updates in place; 417: restating never duplicates.
        a = self.core.learn_language_item("en", ITEM_TYPE_WORD, "a", meaning="x")
        again = self.core.learn_language_item("en", ITEM_TYPE_WORD, "A", meaning="y")
        self.assertEqual((again["id"], again["version"]), (a["id"], 2))
        b = self.core.learn_language_item("en", ITEM_TYPE_WORD, "b")
        self.assertTrue(self.core.relate_language_items(a, b, RELATION_SYNONYM)["created"])
        self.assertFalse(self.core.relate_language_items(b, a, RELATION_SYNONYM)["created"])
        self.assertEqual(self.core.resolve_language_meaning("a", "en").meanings[0]["meaning"], "y")


if __name__ == "__main__":
    unittest.main()
