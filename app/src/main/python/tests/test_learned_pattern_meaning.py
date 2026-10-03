"""
Tests for Prompt 424 - Learned Pattern Meaning Binding.

An explicitly taught meaning/intention is bound to a learned sentence
pattern (`LearnedPatternMeaningBinder`, language_intelligence/
learned_pattern_meaning.py) and exposed when Prompt 421 recognizes the
pattern. Nothing here infers a meaning: every meaning asserted below was
bound by the test itself.

Run directly:
    python -m unittest tests.test_learned_pattern_meaning -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import LanguageLearningStore, ITEM_TYPE_PATTERN
from language_intelligence.language_relationships import LanguageRelationshipStore, item_ref
from language_intelligence.meaning_resolution import REASON_NO_LEARNED_MEANING
from language_intelligence.learned_meaning_disambiguation import (
    LearnedMeaningDisambiguator, STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND,
    REASON_NO_CONTEXT_TERMS, REASON_CONTEXT_MATCHED, REASON_SINGLE_MEANING,
)
from language_intelligence.learned_pattern_matching import (
    LearnedPatternMatcher, STATUS_MATCHED, STATUS_NOT_FOUND as MATCH_NOT_FOUND,
)
from language_intelligence.learned_sentence_structure import LearnedSentenceStructureExtractor
from language_intelligence.learned_pattern_teaching import (
    LearnedPatternTeacher, STATUS_CREATED,
)
from language_intelligence.learned_pattern_meaning import (
    LearnedPatternMeaningBinder, LearnedPatternMeaningResult, PatternMeaningBindingResult,
    ITEM_TYPE_MEANING, RELATION_PATTERN_MEANING,
    STATUS_BOUND, STATUS_ALREADY_BOUND, STATUS_CONFLICT, STATUS_PATTERN_NOT_FOUND, STATUS_INVALID,
    REASON_PATTERN_NOT_MATCHED, REASON_NO_MEANING_FOR_LOCALE, REASON_UNKNOWN_PATTERN,
    ERROR_INVALID_MEANING, ERROR_INVALID_LANGUAGE, ERROR_INVALID_LOCALE,
    ERROR_LOCALE_LANGUAGE_MISMATCH, ERROR_LOCALE_CONFLICTS_WITH_PATTERN,
    ERROR_INVALID_CONFIDENCE, ERROR_INVALID_SOURCE, ERROR_INVALID_EXAMPLES,
    ERROR_INVALID_PATTERN,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.language_understanding_result import LanguageUnderstandingResult

from core.core import Core

LIKE = "من {{X}} را دوست دارم"
MESSAGE = "من چای را دوست دارم"
HAVE = "I have {{thing}}"


class _BindingTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem and the composition Core itself
    builds: ONE learning store, ONE relationship store, the Prompt 421
    matcher, the Prompt 422 extractor, the Prompt 423 teacher and the
    Prompt 424 binder over them."""

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
        self.matcher = LearnedPatternMatcher(self.items)
        self.extractor = LearnedSentenceStructureExtractor(self.matcher)
        self.teacher = LearnedPatternTeacher(self.items)
        self.disambiguator = LearnedMeaningDisambiguator()
        self.binder = LearnedPatternMeaningBinder(self.items, self.rels, self.disambiguator)

    def teach(self, language="fa", pattern=LIKE, **kwargs):
        result = self.teacher.teach(language, pattern, **kwargs)
        self.assertEqual(result.status, STATUS_CREATED, result.errors)
        return result

    def bind(self, meaning="express_preference", language="fa", pattern=LIKE, **kwargs):
        return self.binder.bind(language, pattern, meaning, **kwargs)

    def resolve(self, message=MESSAGE, language="fa", locale=None, **context):
        match = self.matcher.match(message, language=language, locale=locale)
        return self.binder.resolve(match, **context)

    def relationship_count(self):
        return self.memory.query_one(
            "SELECT COUNT(*) AS c FROM language_item_relationships")["c"]

    def event_count(self):
        return self.memory.query_one("SELECT COUNT(*) AS c FROM learning_events")["c"]


# ----------------------------------------------------------------------
class TestPatternWithOneExplicitMeaning(_BindingTestCase):
    """1. A pattern taught with one explicit meaning."""

    def test_binding_is_stored_and_reported(self):
        self.teach()
        result = self.bind()
        self.assertIsInstance(result, PatternMeaningBindingResult)
        self.assertEqual(result.status, STATUS_BOUND)
        self.assertTrue(result.success)
        self.assertTrue(result.created)
        self.assertEqual(result.meaning_name, "express_preference")
        self.assertEqual(self.relationship_count(), 1)

    def test_binding_is_an_ordinary_learned_relationship(self):
        pattern = self.teach()
        self.bind()
        found = self.rels.relationships_for(
            item_ref("fa", ITEM_TYPE_PATTERN, LIKE), relation_type=RELATION_PATTERN_MEANING)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["direction"], "outgoing")
        self.assertEqual(found[0]["from"]["id"], pattern.pattern_id)
        self.assertEqual(found[0]["to"]["item_type"], ITEM_TYPE_MEANING)
        self.assertEqual(found[0]["to"]["key"], "express_preference")

    def test_recognized_message_exposes_the_bound_meaning(self):
        self.teach()
        self.bind()
        result = self.resolve()
        self.assertIsInstance(result, LearnedPatternMeaningResult)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertTrue(result.resolved)
        self.assertEqual(result.meaning_name, "express_preference")
        self.assertEqual(result.reason, REASON_SINGLE_MEANING)
        self.assertEqual(len(result.candidates), 1)

    def test_bindings_for_lists_the_explicit_binding(self):
        self.teach()
        self.bind()
        found = self.binder.bindings_for("fa", LIKE)
        self.assertEqual([c["meaning_name"] for c in found], ["express_preference"])


# ----------------------------------------------------------------------
class TestPatternWithoutMeaning(_BindingTestCase):
    """2. A learned pattern with no explicitly bound meaning."""

    def test_match_is_returned_normally_and_meaning_is_unresolved(self):
        self.teach()
        result = self.resolve()
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_NO_LEARNED_MEANING)
        self.assertIsNone(result.meaning)
        self.assertEqual(result.candidates, [])
        self.assertTrue(result.matched)
        self.assertEqual(result.variables, {"X": "چای"})
        self.assertEqual(result.pattern_match["status"], STATUS_MATCHED)

    def test_a_meaning_stored_inline_on_the_pattern_is_not_a_binding(self):
        # Prompt 421/423's own `meaning` value stays exactly what it was;
        # only an explicit binding is a bound meaning.
        self.items.learn_item("fa", ITEM_TYPE_PATTERN, LIKE, meaning={"intent": "likes_thing"})
        result = self.resolve()
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.pattern_match["meaning"], {"intent": "likes_thing"})

    def test_a_message_that_matches_nothing_has_no_meaning_lookup(self):
        self.teach()
        self.bind()
        result = self.resolve("سلام دنیا")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_PATTERN_NOT_MATCHED)
        self.assertFalse(result.matched)
        self.assertEqual(result.pattern_match["status"], MATCH_NOT_FOUND)


# ----------------------------------------------------------------------
class TestPatternWithMultipleMeanings(_BindingTestCase):
    """3. A pattern may have several explicit meanings; none is picked."""

    def setUp(self):
        super().setUp()
        self.teach("en", HAVE)
        self.bind("express_possession", "en", HAVE, examples=["I have a car and a house"])
        self.bind("express_condition", "en", HAVE, examples=["I have a cold and a fever"])

    def test_every_bound_meaning_is_kept_as_a_candidate(self):
        result = self.resolve("I have a fever", language="en")
        self.assertEqual(
            sorted(c["meaning_name"] for c in result.candidates),
            ["express_condition", "express_possession"])
        self.assertEqual(self.relationship_count(), 2)

    def test_without_context_the_status_is_ambiguous_and_nothing_is_chosen(self):
        result = self.resolve("I have a fever", language="en")
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertTrue(result.ambiguous)
        self.assertIsNone(result.meaning)
        self.assertEqual(result.reason, REASON_NO_CONTEXT_TERMS)
        self.assertEqual(len(result.candidates), 2)

    def test_the_existing_disambiguator_decides_when_context_is_available(self):
        result = self.resolve("I have a fever", language="en",
                              active_topic={"topic": "cold fever"})
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.meaning_name, "express_condition")
        self.assertEqual(result.reason, REASON_CONTEXT_MATCHED)
        # every candidate is still reported, also when one was selected
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.disambiguation["status"], STATUS_RESOLVED)

    def test_context_from_recent_turns_and_nearby_expressions_is_used(self):
        turns = [{"user": "we talked about my car", "assistant": "ok"}]
        result = self.resolve("I have a fever", language="en", conversation_context=turns)
        self.assertEqual(result.meaning_name, "express_possession")
        nearby = self.resolve("I have a fever", language="en", nearby_expressions=["house"])
        self.assertEqual(nearby.meaning_name, "express_possession")

    def test_context_that_fits_no_candidate_stays_ambiguous(self):
        result = self.resolve("I have a fever", language="en",
                              active_topic={"topic": "weather forecast"})
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertIsNone(result.meaning)

    def test_context_that_fits_both_equally_stays_ambiguous(self):
        result = self.resolve("I have a fever", language="en",
                              active_topic={"topic": "car cold"})
        self.assertEqual(result.status, STATUS_AMBIGUOUS)

    def test_the_same_meaning_can_be_bound_to_several_patterns(self):
        self.teach("en", "I own {{thing}}")
        self.bind("express_possession", "en", "I own {{thing}}")
        first = self.resolve("I own a boat", language="en")
        self.assertEqual(first.meaning_name, "express_possession")
        self.assertEqual(
            len(self.items.items_for_language("en", item_type=ITEM_TYPE_MEANING)), 2)


# ----------------------------------------------------------------------
class TestMeaningRetrievalAfterMatching(_BindingTestCase):
    """4. Meaning retrieval keeps the pattern match and its variables."""

    def test_the_prompt_421_match_is_kept_whole_and_unchanged(self):
        self.teach(meaning={"intent": "likes_thing"}, locale="fa-IR", confidence=0.7,
                   source="teacher")
        self.bind()
        match = self.matcher.match(MESSAGE, language="fa")
        before = match.to_dict()
        result = self.binder.resolve(match)
        self.assertEqual(result.pattern_match, before)
        self.assertEqual(match.to_dict(), before)  # the match object was not mutated
        self.assertEqual(result.matched_pattern_id, match.matched_pattern_id)
        self.assertEqual(result.matched_pattern_text, LIKE)

    def test_extracted_variables_are_preserved(self):
        self.teach("fa", "من {{X}} را به {{Y}} می‌دهم")
        self.bind("express_giving", "fa", "من {{X}} را به {{Y}} می‌دهم")
        result = self.resolve("من کتاب را به علی می‌دهم")
        self.assertEqual(result.variables, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(result.to_dict()["variables"], {"X": "کتاب", "Y": "علی"})
        structure = self.extractor.from_match(
            self.matcher.match("من کتاب را به علی می‌دهم", language="fa"))
        self.assertEqual(structure.variables, {"X": "کتاب", "Y": "علی"})

    def test_a_dict_match_is_accepted_like_the_result_object(self):
        self.teach()
        self.bind()
        match = self.matcher.match(MESSAGE, language="fa")
        self.assertEqual(self.binder.resolve(match.to_dict()).meaning_name, "express_preference")

    def test_resolving_writes_nothing(self):
        self.teach()
        self.bind()
        relationships, events = self.relationship_count(), self.event_count()
        for _ in range(3):
            self.resolve()
        self.assertEqual(self.relationship_count(), relationships)
        self.assertEqual(self.event_count(), events)

    def test_ambiguous_or_unresolved_pattern_matches_yield_no_meaning(self):
        # two DIFFERENT patterns match one message (Prompt 421: AMBIGUOUS)
        self.teach("en", "I like {{thing}}")
        self.teach("en", "I {{verb}} tea")
        self.bind("express_preference", "en", "I like {{thing}}")
        result = self.resolve("I like tea", language="en")
        self.assertEqual(result.pattern_match["status"], "AMBIGUOUS")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_PATTERN_NOT_MATCHED)
        self.assertIsNone(result.meaning)


# ----------------------------------------------------------------------
class TestMeaningMetadataPreservation(_BindingTestCase):
    """5. Existing metadata is preserved on the attached meaning."""

    def test_all_metadata_is_carried_on_the_candidate(self):
        self.teach()
        self.bind(locale="fa-IR", confidence=0.65, source="teacher",
                  source_context="taught in the onboarding lesson",
                  examples=["من کتاب را دوست دارم"])
        meaning = self.resolve().meaning
        item = self.items.get_item("fa", ITEM_TYPE_MEANING, "express_preference")
        self.assertEqual(meaning["meaning_id"], item["id"])
        self.assertEqual(meaning["id"], item["id"])
        self.assertEqual(meaning["meaning_name"], "express_preference")
        self.assertEqual(meaning["key"], "express_preference")
        self.assertEqual(meaning["language"], "persian")
        self.assertEqual(meaning["locale"], "fa-IR")
        self.assertEqual(meaning["confidence"], 0.65)
        self.assertEqual(meaning["source"], "teacher")
        self.assertEqual(meaning["source_context"], "taught in the onboarding lesson")
        self.assertEqual(meaning["examples"], ["من کتاب را دوست دارم"])
        self.assertEqual(meaning["learning_method"], "explicit_pattern_meaning_binding")
        self.assertEqual(meaning["relation_type"], RELATION_PATTERN_MEANING)

    def test_binding_result_reports_the_stored_metadata(self):
        self.teach()
        result = self.bind(locale="fa-IR", confidence=0.65, source="teacher",
                           source_context="lesson 1", examples=["من چای را دوست دارم"])
        as_dict = result.to_dict()
        self.assertEqual(as_dict["language"], "persian")
        self.assertEqual(as_dict["locale"], "fa-IR")
        self.assertEqual(as_dict["confidence"], 0.65)
        self.assertEqual(as_dict["source"], "teacher")
        self.assertEqual(as_dict["source_context"], "lesson 1")
        self.assertEqual(as_dict["examples"], ["من چای را دوست دارم"])
        self.assertEqual(as_dict["pattern_text"], LIKE)
        self.assertEqual(as_dict["meaning_name"], "express_preference")

    def test_the_pattern_and_its_own_metadata_are_untouched_by_binding(self):
        self.teach(meaning={"intent": "likes_thing"}, confidence=0.4, source="teacher",
                   examples=["من کتاب را دوست دارم"])
        before = self.items.get_item("fa", ITEM_TYPE_PATTERN, LIKE)
        self.bind()
        after = self.items.get_item("fa", ITEM_TYPE_PATTERN, LIKE)
        self.assertEqual(after, before)

    def test_confidence_is_clamped_like_everywhere_else(self):
        self.teach()
        self.assertEqual(self.bind(confidence=7).confidence, 1.0)


# ----------------------------------------------------------------------
class TestLanguageAwareBinding(_BindingTestCase):
    """6. Bindings belong to one language."""

    def test_the_same_meaning_name_in_two_languages_is_two_items(self):
        self.teach("fa", LIKE)
        self.teach("en", "I like {{X}}")
        self.bind("express_preference", "fa", LIKE)
        self.bind("express_preference", "en", "I like {{X}}")
        fa = self.items.get_item("fa", ITEM_TYPE_MEANING, "express_preference")
        en = self.items.get_item("en", ITEM_TYPE_MEANING, "express_preference")
        self.assertNotEqual(fa["id"], en["id"])
        self.assertEqual(self.resolve().meaning["language"], "persian")
        self.assertEqual(self.resolve("I like tea", language="en").meaning["language"], "english")

    def test_a_binding_is_only_found_for_its_own_language(self):
        self.teach("fa", LIKE)
        self.bind("express_preference", "fa", LIKE)
        # the same text learned under another language has no meaning bound to it
        self.teach("en", LIKE)
        result = self.resolve(MESSAGE, language="en")
        self.assertTrue(result.matched)
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_NO_LEARNED_MEANING)
        self.assertEqual(self.binder.bindings_for("en", LIKE), [])
        self.assertEqual(len(self.binder.bindings_for("fa", LIKE)), 1)

    def test_language_aliases_are_one_language(self):
        self.teach("fa", LIKE)
        self.bind("express_preference", "persian", LIKE)
        self.assertEqual(self.resolve(language="Persian").meaning_name, "express_preference")

    def test_language_is_required_and_validated(self):
        self.teach()
        for bad in ("", "unknown", None):
            result = self.bind(language=bad)
            self.assertEqual(result.status, STATUS_INVALID)
            self.assertIn(ERROR_INVALID_LANGUAGE, [e["code"] for e in result.errors])
        self.assertEqual(self.relationship_count(), 0)


# ----------------------------------------------------------------------
class TestLocaleAwareBinding(_BindingTestCase):
    """7. A binding may be scoped to a locale (Prompt 421's convention)."""

    def setUp(self):
        super().setUp()
        self.teach()

    def test_a_locale_scoped_binding_applies_only_under_that_locale(self):
        self.bind("express_preference", locale="fa-IR")
        self.assertEqual(self.resolve(locale="fa-IR").meaning_name, "express_preference")
        other = self.resolve(locale="fa-AF")
        self.assertEqual(other.status, STATUS_NOT_FOUND)
        self.assertEqual(other.reason, REASON_NO_MEANING_FOR_LOCALE)
        self.assertEqual(other.candidates, [])
        self.assertTrue(other.matched)

    def test_a_binding_without_locale_applies_to_every_locale(self):
        self.bind("express_preference")
        for locale in (None, "fa-IR", "fa-AF"):
            self.assertEqual(self.resolve(locale=locale).meaning_name, "express_preference")

    def test_no_requested_locale_considers_every_binding(self):
        self.bind("express_preference", locale="fa-IR")
        self.bind("express_favor", locale="fa-AF")
        self.assertEqual(len(self.resolve().candidates), 2)

    def test_locale_narrows_between_several_meanings_before_disambiguation(self):
        self.bind("express_preference", locale="fa-IR")
        self.bind("express_favor", locale="fa-AF")
        result = self.resolve(locale="fa-AF")
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.meaning_name, "express_favor")
        self.assertEqual(result.locale, "fa-AF")

    def test_locale_is_validated_and_must_belong_to_the_language(self):
        bad_tag = self.bind(locale="not a locale")
        self.assertEqual(bad_tag.reason, ERROR_INVALID_LOCALE)
        mismatch = self.bind(locale="en-US")
        self.assertEqual(mismatch.reason, ERROR_LOCALE_LANGUAGE_MISMATCH)
        self.assertEqual(self.relationship_count(), 0)

    def test_a_binding_cannot_name_a_locale_its_pattern_is_not_recognized_in(self):
        self.teach("fa", "من {{X}} را می‌خوانم", locale="fa-IR")
        result = self.bind("express_reading", pattern="من {{X}} را می‌خوانم", locale="fa-AF")
        self.assertEqual(result.status, STATUS_INVALID)
        self.assertEqual(result.reason, ERROR_LOCALE_CONFLICTS_WITH_PATTERN)

    def test_rebinding_under_another_locale_is_a_conflict_not_a_rescope(self):
        self.bind("express_preference", locale="fa-IR")
        result = self.bind("express_preference", locale="fa-AF")
        self.assertEqual(result.status, STATUS_CONFLICT)
        self.assertEqual(self.resolve(locale="fa-IR").meaning["locale"], "fa-IR")
        self.assertEqual(self.relationship_count(), 1)


# ----------------------------------------------------------------------
class TestBindingRules(_BindingTestCase):
    """Validation and duplicate handling of `bind()`."""

    def test_an_unknown_pattern_is_refused_and_never_created(self):
        result = self.bind()
        self.assertEqual(result.status, STATUS_PATTERN_NOT_FOUND)
        self.assertEqual(result.reason, REASON_UNKNOWN_PATTERN)
        self.assertFalse(result.success)
        self.assertEqual(self.items.items_for_language("fa"), [])
        self.assertEqual(self.relationship_count(), 0)

    def test_the_meaning_must_be_named_by_the_caller(self):
        self.teach()
        for bad in (None, "", "   ", 5, {"intent": "x"}):
            result = self.bind(meaning=bad)
            self.assertEqual(result.status, STATUS_INVALID)
            self.assertEqual(result.reason, ERROR_INVALID_MEANING)
        self.assertEqual(self.relationship_count(), 0)
        self.assertEqual(self.items.items_for_language("fa", item_type=ITEM_TYPE_MEANING), [])

    def test_all_errors_are_reported_together_and_nothing_is_stored(self):
        self.teach()
        result = self.bind(meaning="", locale="zz zz", confidence="high", source="  ",
                           examples=["ok", 3])
        codes = {e["code"] for e in result.errors}
        self.assertTrue({ERROR_INVALID_MEANING, ERROR_INVALID_LOCALE, ERROR_INVALID_CONFIDENCE,
                         ERROR_INVALID_SOURCE, ERROR_INVALID_EXAMPLES} <= codes)
        self.assertEqual(self.relationship_count(), 0)
        self.assertEqual(self.items.items_for_language("fa", item_type=ITEM_TYPE_MEANING), [])

    def test_a_bad_pattern_argument_is_invalid_and_does_not_raise(self):
        result = self.binder.bind("fa", None, "express_preference")
        self.assertEqual(result.status, STATUS_INVALID)
        self.assertEqual(result.reason, ERROR_INVALID_PATTERN)

    def test_binding_the_same_pair_again_never_duplicates(self):
        self.teach()
        first = self.bind()
        second = self.bind()
        self.assertEqual(second.status, STATUS_ALREADY_BOUND)
        self.assertTrue(second.success)
        self.assertFalse(second.created)
        self.assertEqual(second.updated_fields, [])
        self.assertEqual(self.relationship_count(), 1)
        self.assertEqual(second.binding["binding_id"], first.binding["binding_id"])
        self.assertEqual(
            len(self.items.items_for_language("fa", item_type=ITEM_TYPE_MEANING)), 1)

    def test_an_identical_rebind_writes_nothing(self):
        self.teach()
        self.bind(confidence=0.5, source="teacher", examples=["من چای را دوست دارم"])
        events = self.event_count()
        again = self.bind(confidence=0.5, source="teacher", examples=["من چای را دوست دارم"])
        self.assertEqual(again.updated_fields, [])
        self.assertEqual(self.event_count(), events)

    def test_only_supplied_metadata_changes_and_examples_are_added(self):
        self.teach()
        self.bind(confidence=0.5, source="teacher", source_context="lesson 1",
                  locale="fa-IR", examples=["یک"])
        again = self.bind(confidence=0.9, examples=["یک", "دو"])
        self.assertEqual(sorted(again.updated_fields), ["confidence", "examples"])
        binding = self.binder.bindings_for("fa", LIKE)[0]
        self.assertEqual(binding["confidence"], 0.9)
        self.assertEqual(binding["examples"], ["یک", "دو"])
        self.assertEqual(binding["source"], "teacher")
        self.assertEqual(binding["source_context"], "lesson 1")
        self.assertEqual(binding["locale"], "fa-IR")

    def test_binding_does_not_change_what_teaching_or_matching_report(self):
        taught = self.teach()
        self.bind()
        again = self.teacher.teach("fa", LIKE)
        self.assertEqual(again.pattern_id, taught.pattern_id)
        self.assertEqual(again.updated_fields, [])
        self.assertEqual(again.status, "ALREADY_EXISTS")


# ----------------------------------------------------------------------
class TestPersistence(_BindingTestCase):
    """8. The binding survives a reload of the existing storage."""

    def test_binding_and_metadata_survive_a_reopened_memory_system(self):
        self.teach(locale="fa-IR")
        self.bind("express_preference", locale="fa-IR", confidence=0.8, source="teacher",
                  source_context="lesson 1", examples=["من کتاب را دوست دارم"])
        self.bind("express_favor")
        before = self.resolve(locale="fa-IR").to_dict()
        self._open()  # brand-new MemorySystem / stores on the same file
        after = self.resolve(locale="fa-IR").to_dict()
        self.assertEqual(after, before)
        self.assertEqual(len(after["candidates"]), 2)
        preference = [c for c in after["candidates"] if c["meaning_name"] == "express_preference"][0]
        self.assertEqual(preference["confidence"], 0.8)
        self.assertEqual(preference["source_context"], "lesson 1")

    def test_a_duplicate_is_still_not_created_after_reload(self):
        self.teach()
        self.bind()
        self._open()
        self.assertEqual(self.bind().status, STATUS_ALREADY_BOUND)
        self.assertEqual(self.relationship_count(), 1)

    def test_core_bindings_persist_across_a_new_core_on_the_same_database(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            db = os.path.join(tmp.name, "core.db")
            first = Core(memory_db_path=db)
            first.teach_sentence_pattern("fa", LIKE)
            self.assertEqual(
                first.bind_pattern_meaning("fa", LIKE, "express_preference").status, STATUS_BOUND)
            second = Core(memory_db_path=db)
            result = second.resolve_pattern_meaning(MESSAGE, language="fa")
            self.assertEqual(result.status, STATUS_RESOLVED)
            self.assertEqual(result.meaning_name, "express_preference")
            self.assertEqual(result.variables, {"X": "چای"})
        finally:
            tmp.cleanup()


# ----------------------------------------------------------------------
class TestUnderstandingEngineIntegration(_BindingTestCase):
    """9. The bound meaning is exposed through LanguageUnderstandingResult."""

    def make_lic(self, with_binder=True):
        backend = DeterministicFallbackBackend(
            UnderstandingEngine(), pattern_matcher=self.matcher,
            structure_extractor=self.extractor,
            pattern_meaning_binder=self.binder if with_binder else None)
        return LanguageIntelligenceCore(backend=backend)

    def test_a_recognized_message_exposes_everything(self):
        self.teach(locale="fa-IR")
        self.bind(locale="fa-IR", confidence=0.9, source="teacher")
        result = self.make_lic().understand(MESSAGE)
        self.assertIsInstance(result, LanguageUnderstandingResult)
        bound = result.learned_pattern_meaning
        self.assertIsNotNone(bound)
        self.assertEqual(bound["status"], STATUS_RESOLVED)
        self.assertEqual(bound["meaning"]["meaning_name"], "express_preference")
        self.assertEqual(bound["variables"], {"X": "چای"})
        self.assertEqual(bound["original_message"], MESSAGE)
        self.assertEqual(bound["language"], result.detected_language)
        self.assertEqual(bound["candidates"][0]["confidence"], 0.9)
        self.assertEqual(bound["matched_pattern_text"], LIKE)
        # alongside the other Prompt 421/422 information, all consistent
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)
        self.assertEqual(result.learned_pattern_match["variables"], {"X": "چای"})
        self.assertEqual(result.learned_sentence_structure["status"], STATUS_MATCHED)
        self.assertEqual(bound["pattern_match"], result.learned_pattern_match)
        self.assertEqual(result.to_dict()["learned_pattern_meaning"], bound)

    def test_original_message_is_the_users_untouched_text(self):
        self.teach()
        self.bind()
        messy = "  من   چای را   دوست دارم  "
        result = self.make_lic().understand(messy)
        self.assertEqual(result.original_input, messy)
        self.assertEqual(result.learned_pattern_meaning["original_message"], messy)
        self.assertEqual(result.learned_pattern_meaning["status"], STATUS_RESOLVED)

    def test_ambiguity_is_reported_through_the_result(self):
        self.teach()
        self.bind("express_preference")
        self.bind("express_favor")
        bound = self.make_lic().understand(MESSAGE).learned_pattern_meaning
        self.assertEqual(bound["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(bound["meaning"])
        self.assertEqual(len(bound["candidates"]), 2)

    def test_context_the_backend_already_has_reaches_the_disambiguator(self):
        # The message's own other candidate expressions (the Understanding
        # Engine's entities) are the `nearby_expressions` of Prompt 420.
        self.teach("en", HAVE)
        self.bind("express_possession", "en", HAVE, examples=["I have a car"])
        self.bind("express_condition", "en", HAVE, examples=["I have a fever"])
        bound = self.make_lic().understand("I have a fever today").learned_pattern_meaning
        self.assertEqual(bound["status"], STATUS_RESOLVED)
        self.assertEqual(bound["meaning"]["meaning_name"], "express_condition")
        self.assertEqual(len(bound["candidates"]), 2)
        self.assertEqual(bound["disambiguation"]["reason"], REASON_CONTEXT_MATCHED)

    def test_pattern_without_a_meaning_is_not_found_but_still_matched(self):
        self.teach()
        result = self.make_lic().understand(MESSAGE)
        bound = result.learned_pattern_meaning
        self.assertEqual(bound["status"], STATUS_NOT_FOUND)
        self.assertEqual(bound["reason"], REASON_NO_LEARNED_MEANING)
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)

    def test_no_binder_reproduces_the_previous_result(self):
        self.teach()
        self.bind()
        with_binder = self.make_lic(True).understand(MESSAGE)
        without = self.make_lic(False).understand(MESSAGE)
        self.assertIsNone(without.learned_pattern_meaning)
        left, right = with_binder.to_dict(), without.to_dict()
        left.pop("learned_pattern_meaning")
        right.pop("learned_pattern_meaning")
        # Prompt 425: `response_plan` is DERIVED from learned_pattern_meaning
        # (a plan made with a binder differs from one made without it by
        # design), so it is excluded here exactly as its source field is.
        # Every other field must still be identical.
        left.pop("response_plan")
        right.pop("response_plan")
        self.assertEqual(left, right)

    def test_no_pattern_match_means_no_meaning_result(self):
        backend = DeterministicFallbackBackend(
            UnderstandingEngine(), pattern_meaning_binder=self.binder)
        result = LanguageIntelligenceCore(backend=backend).understand(MESSAGE)
        self.assertIsNone(result.learned_pattern_meaning)

    def test_a_binder_failure_never_breaks_understanding(self):
        class Broken:
            def resolve(self, *args, **kwargs):
                raise RuntimeError("boom")

        self.teach()
        backend = DeterministicFallbackBackend(
            UnderstandingEngine(), pattern_matcher=self.matcher, pattern_meaning_binder=Broken())
        result = LanguageIntelligenceCore(backend=backend).understand(MESSAGE)
        self.assertIsNone(result.learned_pattern_meaning)
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)
        self.assertTrue(any("learned_pattern_meaning_error" in w for w in result.warnings))

    def test_core_wires_its_own_binder_into_the_conversation_path(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            core = Core(memory_db_path=os.path.join(tmp.name, "core.db"))
            self.assertIsInstance(core.pattern_meaning_binder, LearnedPatternMeaningBinder)
            self.assertIs(core.pattern_meaning_binder.disambiguator, core.meaning_disambiguator)
            core.teach_sentence_pattern("english", "I love {{thing}}")
            core.bind_pattern_meaning("english", "I love {{thing}}", "express_preference")
            core.process_input("I love tea")
            bound = core.last_language_understanding.learned_pattern_meaning
            self.assertIsNotNone(bound)
            self.assertEqual(bound["meaning"]["meaning_name"], "express_preference")
            self.assertEqual(bound["variables"], {"thing": "tea"})
            self.assertEqual(bound["original_message"], "I love tea")
        finally:
            tmp.cleanup()

    def test_core_resolve_pattern_meaning_passthrough(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            core = Core(memory_db_path=os.path.join(tmp.name, "core.db"))
            core.teach_sentence_pattern("fa", LIKE, locale="fa-IR")
            core.bind_pattern_meaning("fa", LIKE, "express_preference", locale="fa-IR")
            hit = core.resolve_pattern_meaning(MESSAGE, language="fa", locale="fa-IR")
            self.assertEqual(hit.meaning_name, "express_preference")
            miss = core.resolve_pattern_meaning("سلام", language="fa")
            self.assertEqual(miss.status, STATUS_NOT_FOUND)
            self.assertEqual(miss.reason, REASON_PATTERN_NOT_MATCHED)
        finally:
            tmp.cleanup()


# ----------------------------------------------------------------------
class TestRegressions(_BindingTestCase):
    """10-12. Prompts 421, 422 and 423 behave exactly as before."""

    def test_prompt_421_match_is_identical_with_and_without_bindings(self):
        self.teach(meaning={"intent": "likes_thing"})
        before = self.matcher.match(MESSAGE, language="fa").to_dict()
        self.bind("express_preference")
        self.bind("express_favor")
        after = self.matcher.match(MESSAGE, language="fa").to_dict()
        self.assertEqual(after, before)
        self.assertEqual(after["meaning"], {"intent": "likes_thing"})
        self.assertNotIn("meaning_binding", after)

    def test_prompt_421_never_matches_a_meaning_item_as_a_pattern(self):
        self.teach()
        self.bind("من {{X}} را دوست دارم")  # a meaning whose text looks like a pattern
        candidates = self.matcher._collect_patterns("fa", 50)[0]
        self.assertEqual([c["key"] for c in candidates], [LIKE])

    def test_prompt_422_structure_is_identical_with_and_without_bindings(self):
        self.teach()
        before = self.extractor.extract(MESSAGE, language="fa").to_dict()
        self.bind()
        after = self.extractor.extract(MESSAGE, language="fa").to_dict()
        self.assertEqual(after, before)
        self.assertEqual([c["kind"] for c in after["components"]],
                         ["fixed", "variable", "fixed"])

    def test_prompt_423_teaching_results_are_unchanged(self):
        created = self.teacher.teach("fa", LIKE, meaning={"intent": "likes_thing"},
                                     locale="fa-IR", examples=["من کتاب را دوست دارم"])
        self.assertEqual(created.status, STATUS_CREATED)
        self.bind()
        self.assertEqual(sorted(created.to_dict()), sorted(self.teacher.teach(
            "fa", LIKE).to_dict()))
        again = self.teacher.teach("fa", LIKE)
        self.assertEqual(again.status, "ALREADY_EXISTS")
        self.assertEqual(again.meaning, {"intent": "likes_thing", "locale": "fa-IR"})
        invalid = self.teacher.teach("fa", "{{X}}")
        self.assertEqual(invalid.status, "INVALID")


# ----------------------------------------------------------------------
class TestNoAutomaticMeaningInvention(_BindingTestCase):
    """14. Nothing here ever creates a meaning the caller did not bind."""

    def test_teaching_a_pattern_never_creates_a_meaning_or_binding(self):
        self.teach(meaning={"intent": "likes_thing"}, examples=["من کتاب را دوست دارم"])
        self.assertEqual(self.items.items_for_language("fa", item_type=ITEM_TYPE_MEANING), [])
        self.assertEqual(self.relationship_count(), 0)

    def test_resolving_never_creates_meanings_or_bindings(self):
        self.teach(meaning={"intent": "likes_thing"})
        for _ in range(2):
            result = self.resolve()
            self.assertIsNone(result.meaning)
        self.assertEqual(self.items.items_for_language("fa", item_type=ITEM_TYPE_MEANING), [])
        self.assertEqual(self.relationship_count(), 0)

    def test_a_failed_bind_leaves_no_meaning_item_behind(self):
        result = self.bind()  # pattern never taught
        self.assertEqual(result.status, STATUS_PATTERN_NOT_FOUND)
        self.assertEqual(self.items.items_for_language("fa", item_type=ITEM_TYPE_MEANING), [])

    def test_a_meaning_bound_to_one_pattern_is_not_borrowed_by_a_similar_one(self):
        self.teach("fa", LIKE)
        self.teach("fa", "من {{X}} را دوست ندارم")
        self.bind("express_preference", "fa", LIKE)
        result = self.resolve("من چای را دوست ندارم")
        self.assertTrue(result.matched)
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertIsNone(result.meaning)

    def test_variables_and_examples_never_become_meanings(self):
        self.teach(examples=["من کتاب را دوست دارم"])
        result = self.resolve()
        self.assertEqual(result.variables, {"X": "چای"})
        self.assertEqual(result.candidates, [])
        self.assertIsNone(result.meaning_name)


# ----------------------------------------------------------------------
class TestOriginalMessagePreservation(_BindingTestCase):
    """15. The original message is reported verbatim."""

    def test_the_message_is_never_normalized_or_rewritten(self):
        self.teach()
        self.bind()
        messy = "  من\u00a0 چای   را دوست دارم "
        result = self.resolve(messy)
        self.assertEqual(result.original_message, messy)
        self.assertEqual(result.to_dict()["original_message"], messy)
        self.assertEqual(result.pattern_match["original_message"], messy)

    def test_an_explicit_original_message_overrides_only_the_reported_text(self):
        self.teach()
        self.bind()
        match = self.matcher.match("من چای را دوست دارم", language="fa")
        result = self.binder.resolve(match, original_message="  من چای را دوست دارم!  ")
        self.assertEqual(result.original_message, "  من چای را دوست دارم!  ")
        self.assertEqual(result.pattern_match["original_message"], "من چای را دوست دارم")

    def test_an_unmatched_message_is_preserved_too(self):
        result = self.resolve("  hello there  ", language="en")
        self.assertEqual(result.original_message, "  hello there  ")
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_result_is_json_shaped(self):
        import json
        self.teach()
        self.bind(examples=["من کتاب را دوست دارم"])
        json.dumps(self.resolve().to_dict(), ensure_ascii=False)
        json.dumps(self.bind().to_dict(), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
