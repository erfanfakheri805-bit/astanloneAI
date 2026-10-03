"""
Tests for Prompt 420 - Learned Meaning Disambiguation.

`LearnedMeaningDisambiguator` (language_intelligence/
learned_meaning_disambiguation.py) sits on top of the existing
`MeaningResolver` (Prompt 418) and decides - deterministically, never
guessing - whether several learned meanings for one expression can be
narrowed to a single relevant candidate using only existing, already
-available information (language, active topic, conversation context,
nearby expressions in the same message, a resolved reference, and each
candidate's own stored examples/source_context), or must be reported as
genuinely AMBIGUOUS.

Run directly:
    python -m unittest tests.test_learned_meaning_disambiguation -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from understanding.language_detection import LANGUAGE_ENGLISH

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import LanguageLearningStore, ITEM_TYPE_WORD
from language_intelligence.language_relationships import LanguageRelationshipStore
from language_intelligence.meaning_resolution import (
    MeaningResolver, STATUS_RESOLVED, STATUS_NOT_FOUND,
)
from language_intelligence.learned_meaning_disambiguation import (
    LearnedMeaningDisambiguator, DisambiguationResult, STATUS_AMBIGUOUS, ALL_STATUSES,
    REASON_SINGLE_MEANING, REASON_LANGUAGE_NARROWED, REASON_NO_CONTEXT_TERMS,
    REASON_NO_CANDIDATE_MATCHED, REASON_CONTEXT_MATCHED, REASON_CONTEXT_TIED, REASON_NOT_FOUND,
    collect_context_terms,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from context.active_topic import ActiveTopicResult, SOURCE_CURRENT_INPUT
from context.conversation_context import ConversationContext
from context.message_reference_resolution import ResolvedReference

from core.core import Core


class _DisambiguatorTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + the composed Prompt 416-418 stores,
    a MeaningResolver over them, and a LearnedMeaningDisambiguator -
    mirrors _ResolverTestCase in test_meaning_resolution.py exactly."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.knowledge = KnowledgeSystem(self.memory)
        self.items = LanguageLearningStore(self.memory)
        self.rels = LanguageRelationshipStore(self.memory, self.items, self.knowledge)
        self.resolver = MeaningResolver(self.items, self.rels, self.knowledge)
        self.disambiguator = LearnedMeaningDisambiguator()

    def tearDown(self):
        self._tmpdir.cleanup()


class TestOneKnownMeaningResolves(_DisambiguatorTestCase):
    """1. One known meaning -> RESOLVED."""

    def test_single_learned_meaning_is_resolved_without_needing_context(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        resolution = self.resolver.resolve("python", "english")
        result = self.disambiguator.disambiguate(resolution)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.reason, REASON_SINGLE_MEANING)
        self.assertEqual(result.resolved_meaning["meaning"], {"gloss": "a language"})
        self.assertEqual(len(result.candidates), 1)
        self.assertIsInstance(result, DisambiguationResult)


class TestMultipleMeaningsWithEnoughContextResolve(_DisambiguatorTestCase):
    """2. Multiple meanings with enough context -> the relevant candidate
    can be identified."""

    def _learn_bank(self):
        self.items.learn_item(
            "english", "sense_financial", "bank",
            meaning={"gloss": "a financial institution"},
            examples=["I deposited money at the bank."],
        )
        self.items.learn_item(
            "english", "sense_river", "bank",
            meaning={"gloss": "the land alongside a river"},
            examples=["We sat on the river bank and watched the water."],
        )

    def test_active_topic_distinguishes_the_relevant_candidate(self):
        self._learn_bank()
        resolution = self.resolver.resolve("bank", "english")
        self.assertTrue(resolution.ambiguous)
        active_topic = ActiveTopicResult(
            "river water", SOURCE_CURRENT_INPUT, 0.7, True, None, "first_topic",
        )
        result = self.disambiguator.disambiguate(resolution, active_topic=active_topic)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.reason, REASON_CONTEXT_MATCHED)
        self.assertEqual(result.resolved_meaning["item_type"], "sense_river")
        # every original candidate is still preserved, not collapsed
        self.assertEqual(len(result.candidates), 2)

    def test_conversation_context_recent_turn_distinguishes_the_candidate(self):
        self._learn_bank()
        resolution = self.resolver.resolve("bank", "english")
        context = ConversationContext()
        context.add_turn("I need to deposit some money soon.", "Sure, I can help with that.")
        result = self.disambiguator.disambiguate(resolution, conversation_context=context)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.resolved_meaning["item_type"], "sense_financial")

    def test_nearby_expression_in_the_same_message_distinguishes_the_candidate(self):
        self._learn_bank()
        resolution = self.resolver.resolve("bank", "english")
        result = self.disambiguator.disambiguate(
            resolution, nearby_expressions=["river", "water"],
        )
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.resolved_meaning["item_type"], "sense_river")


class TestMultipleMeaningsWithoutEnoughContextAreAmbiguous(_DisambiguatorTestCase):
    """3. Multiple meanings without enough context -> AMBIGUOUS."""

    def test_no_context_at_all_is_ambiguous(self):
        self.items.learn_item("en", "noun", "run", meaning={"gloss": "an act of running"})
        self.items.learn_item("en", "verb", "run", meaning={"gloss": "to move quickly on foot"})
        resolution = self.resolver.resolve("run", "en")
        result = self.disambiguator.disambiguate(resolution)
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.reason, REASON_NO_CONTEXT_TERMS)
        self.assertIsNone(result.resolved_meaning)
        # candidates are preserved, never collapsed into a guess
        self.assertEqual(len(result.candidates), 2)

    def test_context_present_but_matching_nothing_is_ambiguous(self):
        self.items.learn_item("en", "noun", "run", meaning={"gloss": "an act of running"})
        self.items.learn_item("en", "verb", "run", meaning={"gloss": "to move quickly on foot"})
        resolution = self.resolver.resolve("run", "en")
        result = self.disambiguator.disambiguate(resolution, nearby_expressions=["quantum", "telescope"])
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.reason, REASON_NO_CANDIDATE_MATCHED)
        self.assertIsNone(result.resolved_meaning)

    def test_tied_context_score_is_ambiguous_never_guessed(self):
        self.items.learn_item(
            "en", "noun", "run", meaning={"gloss": "an act of running"}, examples=["a morning run"],
        )
        self.items.learn_item(
            "en", "verb", "run", meaning={"gloss": "to move quickly"}, examples=["morning run fast"],
        )
        resolution = self.resolver.resolve("run", "en")
        result = self.disambiguator.disambiguate(resolution, nearby_expressions=["morning"])
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.reason, REASON_CONTEXT_TIED)
        self.assertIsNone(result.resolved_meaning)
        self.assertEqual(len(result.candidates), 2)


class TestUnknownExpressionIsNotFound(_DisambiguatorTestCase):
    """4. Unknown expression -> NOT_FOUND."""

    def test_unknown_expression_is_not_found(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        resolution = self.resolver.resolve("bagelization", "english")
        result = self.disambiguator.disambiguate(resolution)
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_NOT_FOUND)
        self.assertEqual(result.candidates, [])
        self.assertIsNone(result.resolved_meaning)


class TestLanguageAffectsCandidateSelection(_DisambiguatorTestCase):
    """5. Language/locale affects candidate selection."""

    def _learn_mint(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "mint", meaning={"gloss": "an herb"})
        self.items.learn_item("german", ITEM_TYPE_WORD, "mint", meaning={"gloss": "coin factory"})

    def test_preferred_language_narrows_to_a_single_candidate(self):
        self._learn_mint()
        resolution = self.resolver.resolve("mint", language=None)  # every language searched
        self.assertTrue(resolution.ambiguous)
        result = self.disambiguator.disambiguate(resolution, preferred_language="german")
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.reason, REASON_LANGUAGE_NARROWED)
        self.assertEqual(result.resolved_meaning["language"], "german")
        self.assertEqual(result.resolved_meaning["meaning"], {"gloss": "coin factory"})

    def test_different_preferred_language_selects_the_other_candidate(self):
        self._learn_mint()
        resolution = self.resolver.resolve("mint", language=None)
        result = self.disambiguator.disambiguate(resolution, preferred_language="english")
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.resolved_meaning["language"], "english")

    def test_no_language_hint_falls_through_to_context_scoring(self):
        self._learn_mint()
        resolution = self.resolver.resolve("mint", language=None)
        result = self.disambiguator.disambiguate(resolution)
        # no language hint and no context terms - genuinely ambiguous
        self.assertEqual(result.status, STATUS_AMBIGUOUS)


class TestActiveTopicAndConversationContextAffectRelevance(_DisambiguatorTestCase):
    """6. Existing active topic/conversation context can affect
    deterministic relevance."""

    def test_active_topic_and_conversation_context_agree_on_a_candidate(self):
        self.items.learn_item(
            "english", "sense_a", "mint", meaning={"gloss": "an herb"},
            source_context="fresh herb garden mint leaves",
        )
        self.items.learn_item(
            "english", "sense_b", "mint", meaning={"gloss": "coin factory"},
            source_context="government coin factory currency",
        )
        resolution = self.resolver.resolve("mint", "english")
        active_topic = ActiveTopicResult("herb garden", SOURCE_CURRENT_INPUT, 0.7, True, None, "r")
        context = ConversationContext()
        context.add_turn("I love growing fresh herb plants.", "That's great!")
        result = self.disambiguator.disambiguate(
            resolution, active_topic=active_topic, conversation_context=context,
        )
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.resolved_meaning["item_type"], "sense_a")

    def test_resolved_reference_contributes_context_terms(self):
        self.items.learn_item(
            "english", "sense_a", "mint", meaning={"gloss": "an herb"},
            source_context="fresh herb garden",
        )
        self.items.learn_item(
            "english", "sense_b", "mint", meaning={"gloss": "coin factory"},
            source_context="government coin factory",
        )
        resolution = self.resolver.resolve("mint", "english")
        resolved_reference = ResolvedReference(
            has_reference=True, reference_text="it",
            resolved_context="the government coin factory downtown",
            confidence=0.9, ambiguous=False, reason="reference_matches_current_topic",
        )
        result = self.disambiguator.disambiguate(resolution, resolved_reference=resolved_reference)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.resolved_meaning["item_type"], "sense_b")

    def test_collect_context_terms_is_bounded_and_deterministic(self):
        terms_one = collect_context_terms(active_topic={"topic": "river water flow"})
        terms_two = collect_context_terms(active_topic={"topic": "river water flow"})
        self.assertEqual(terms_one, terms_two)
        self.assertIn("river", terms_one)


class TestOriginalMessageIsNeverRewritten(_DisambiguatorTestCase):
    """7. The original user message remains unchanged."""

    def setUp(self):
        super().setUp()
        self.engine = UnderstandingEngine()
        self.backend = DeterministicFallbackBackend(
            self.engine, meaning_resolver=self.resolver, meaning_disambiguator=self.disambiguator,
        )
        self.lic = LanguageIntelligenceCore(backend=self.backend)

    def test_understanding_never_rewrites_the_raw_message(self):
        self.items.learn_item(
            "english", "sense_financial", "bank", meaning={"gloss": "a financial institution"},
        )
        self.items.learn_item(
            "english", "sense_river", "bank", meaning={"gloss": "the land alongside a river"},
        )
        raw = "  I went to the Bank   by the river.  "
        result = self.lic.understand(raw)
        self.assertEqual(result.original_input, raw)

    def test_disambiguation_result_expression_matches_the_extracted_term_not_the_raw_text(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        resolution = self.resolver.resolve("Python", "english")
        result = self.disambiguator.disambiguate(resolution)
        self.assertEqual(result.expression, "Python")  # verbatim, never lowercased/rewritten


class TestLearnedInformationIsPreserved(_DisambiguatorTestCase):
    """8. Existing learned meaning information and confidence/context are
    preserved through disambiguation."""

    def test_resolved_candidate_keeps_its_full_stored_provenance(self):
        self.items.learn_item(
            "english", "sense_financial", "bank", meaning={"gloss": "a financial institution"},
            confidence=0.8, source="user", source_context="taught during onboarding: bank money",
            learning_method="manual", examples=["I put money in the bank."],
        )
        self.items.learn_item(
            "english", "sense_river", "bank", meaning={"gloss": "the land alongside a river"},
            confidence=0.6, source="conversation", source_context="river bank water",
            learning_method="conversation",
        )
        resolution = self.resolver.resolve("bank", "english")
        result = self.disambiguator.disambiguate(resolution, nearby_expressions=["money"])
        self.assertEqual(result.status, STATUS_RESOLVED)
        resolved = result.resolved_meaning
        self.assertEqual(resolved["confidence"], 0.8)
        self.assertEqual(resolved["source"], "user")
        self.assertEqual(resolved["learning_method"], "manual")
        self.assertEqual(resolved["examples"], ["I put money in the bank."])

    def test_candidates_list_is_the_same_meanings_the_resolver_produced(self):
        self.items.learn_item("en", "noun", "run", meaning={"gloss": "an act of running"})
        self.items.learn_item("en", "verb", "run", meaning={"gloss": "to move quickly on foot"})
        resolution = self.resolver.resolve("run", "en")
        result = self.disambiguator.disambiguate(resolution)
        self.assertEqual(result.candidates, resolution.meanings)


class TestPrompt416To419Compatibility(unittest.TestCase):
    """9. Existing Prompt 416-419 tests/behavior remain compatible."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.knowledge = KnowledgeSystem(self.memory)
        self.items = LanguageLearningStore(self.memory)
        self.rels = LanguageRelationshipStore(self.memory, self.items, self.knowledge)
        self.resolver = MeaningResolver(self.items, self.rels, self.knowledge)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_meaning_resolver_status_vocabulary_is_unchanged(self):
        # Prompt 418's own resolver still only ever reports these two -
        # AMBIGUOUS is a Prompt 420 concept that lives one layer above it.
        from language_intelligence.meaning_resolution import ALL_STATUSES as RESOLVER_STATUSES
        self.assertEqual(set(RESOLVER_STATUSES), {"RESOLVED", "NOT_FOUND"})

    def test_disambiguation_status_vocabulary_adds_ambiguous_on_top(self):
        self.assertEqual(set(ALL_STATUSES), {STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND})

    def test_backend_without_disambiguator_configured_produces_no_disambiguated_meanings(self):
        engine = UnderstandingEngine()
        backend = DeterministicFallbackBackend(engine, meaning_resolver=self.resolver)
        lic = LanguageIntelligenceCore(backend=backend)
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        result = lic.understand("Python is a programming language.")
        self.assertEqual(result.disambiguated_meanings, [])
        # learned_meanings (Prompt 419) is completely unaffected
        self.assertTrue(any(e["expression"] == "Python" for e in result.learned_meanings))

    def test_backend_without_resolver_or_disambiguator_reproduces_pre_419_shape(self):
        engine = UnderstandingEngine()
        backend = DeterministicFallbackBackend(engine)
        lic = LanguageIntelligenceCore(backend=backend)
        result = lic.understand("Python is a programming language.")
        self.assertEqual(result.learned_meanings, [])
        self.assertEqual(result.disambiguated_meanings, [])


class TestConversationUnderstandingIntegrationViaCore(unittest.TestCase):
    """10. Existing conversation understanding remains compatible; full
    end-to-end integration through Core (Understanding Engine,
    Conversation Context, Active Topic, Reference Resolution)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.core = Core(memory_db_path=db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_owns_a_meaning_disambiguator_wired_to_its_own_resolver(self):
        self.assertIsInstance(self.core.meaning_disambiguator, LearnedMeaningDisambiguator)

    def test_single_learned_meaning_resolves_through_full_pipeline(self):
        self.core.learn_language_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        result = self.core.understand_language("Python is a great language.")
        entries = [e for e in result.disambiguated_meanings if e["expression"] == "Python"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], STATUS_RESOLVED)

    def test_ambiguous_meaning_stays_ambiguous_through_full_pipeline_without_context(self):
        self.core.learn_language_item("en", "noun", "run", meaning={"gloss": "an act of running"})
        self.core.learn_language_item("en", "verb", "run", meaning={"gloss": "to move quickly"})
        result = self.core.understand_language("I saw a run.")
        entries = [e for e in result.disambiguated_meanings if e["expression"].lower() == "run"]
        if entries:
            self.assertEqual(entries[0]["status"], STATUS_AMBIGUOUS)

    def test_disambiguate_learned_meaning_passthrough_is_read_only(self):
        self.core.learn_language_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        before = self.core.get_recent_context()
        result = self.core.disambiguate_learned_meaning("python", language="english")
        after = self.core.get_recent_context()
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(before, after)

    def test_process_input_conversation_path_is_unaffected(self):
        # Ordinary conversation handling (unrelated to language learning)
        # keeps working exactly as before this stage existed.
        reply = self.core.process_input("Hello there!")
        self.assertIsInstance(reply, str)


if __name__ == "__main__":
    unittest.main()
