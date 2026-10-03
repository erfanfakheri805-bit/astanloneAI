"""
Tests for Prompt 421 - Learned Sentence Pattern Recognition, integrated
into message understanding.

`DeterministicFallbackBackend.understand()` (language_intelligence/
deterministic_fallback_backend.py) can optionally be given a
`LearnedPatternMatcher` (Prompt 421, learned_pattern_matching.py). When
it is, the `LanguageUnderstandingResult` it returns carries a
`learned_pattern_match` field: one `LearnedPatternMatchResult.to_dict()`
describing whether the message as a whole is recognized as an instance
of a previously learned sentence pattern. Nothing here re-implements the
Understanding Engine, the Language Learning Store (Prompt 416), or the
matcher itself (Prompt 421) - this stage only wires them together,
exactly as Prompt 419 wired the meaning resolver into the same backend.

Run directly:
    python -m unittest tests.test_learned_pattern_matching_in_understanding -v
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
from language_intelligence.language_relationships import LanguageRelationshipStore
from language_intelligence.meaning_resolution import MeaningResolver
from language_intelligence.learned_meaning_disambiguation import LearnedMeaningDisambiguator
from language_intelligence.learned_pattern_matching import (
    LearnedPatternMatcher, STATUS_MATCHED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.language_understanding_result import LanguageUnderstandingResult

from core.core import Core


class _BaseTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + LanguageLearningStore (Prompt 416)
    + LearnedPatternMatcher (Prompt 421), and a DeterministicFallbackBackend
    wired to it - the exact composition Core itself builds (see
    core/core.py's __init__)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.items = LanguageLearningStore(self.memory)
        self.pattern_matcher = LearnedPatternMatcher(self.items)
        self.engine = UnderstandingEngine()
        self.backend = DeterministicFallbackBackend(self.engine, pattern_matcher=self.pattern_matcher)
        self.lic = LanguageIntelligenceCore(backend=self.backend)

    def tearDown(self):
        self._tmpdir.cleanup()


class TestLearnedPatternIsExposedDuringUnderstanding(_BaseTestCase):
    """A message matching a learned pattern exposes the match through
    LanguageUnderstandingResult."""

    def test_matching_message_reports_matched_status(self):
        self.items.learn_item(
            "english", ITEM_TYPE_PATTERN, "I love {{thing}}", meaning={"intent": "likes_thing"},
        )
        result = self.lic.understand("I love tea")
        self.assertIsNotNone(result.learned_pattern_match)
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)
        self.assertEqual(result.learned_pattern_match["variables"], {"thing": "tea"})
        self.assertEqual(result.learned_pattern_match["meaning"], {"intent": "likes_thing"})

    def test_result_carries_the_new_field_in_to_dict(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.lic.understand("I love tea")
        as_dict = result.to_dict()
        self.assertIn("learned_pattern_match", as_dict)
        self.assertEqual(as_dict["learned_pattern_match"]["status"], STATUS_MATCHED)

    def test_isinstance_check(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.lic.understand("hello there")
        self.assertIsInstance(result, LanguageUnderstandingResult)


class TestNoMatcherConfiguredIsUnaffected(unittest.TestCase):
    """No pattern_matcher given (the pre-Prompt-421 default) reproduces
    exactly the old behaviour: learned_pattern_match stays None."""

    def setUp(self):
        self.engine = UnderstandingEngine()
        self.backend = DeterministicFallbackBackend(self.engine)
        self.lic = LanguageIntelligenceCore(backend=self.backend)

    def test_learned_pattern_match_is_none_without_a_matcher(self):
        result = self.lic.understand("I love tea")
        self.assertIsNone(result.learned_pattern_match)

    def test_existing_fields_still_populated(self):
        result = self.lic.understand("I love tea")
        self.assertEqual(result.original_input, "I love tea")
        self.assertTrue(len(result.entities) >= 0)


class TestUnmatchedMessageIsHonestlyNotFound(_BaseTestCase):
    """An unrecognized message is never given a fabricated match."""

    def test_no_learned_pattern_at_all_is_not_found(self):
        result = self.lic.understand("The weather is nice today")
        self.assertEqual(result.learned_pattern_match["status"], STATUS_NOT_FOUND)
        self.assertFalse(result.learned_pattern_match["matched"])

    def test_close_but_unlearned_structure_is_not_found(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.lic.understand("I hate broccoli")
        self.assertEqual(result.learned_pattern_match["status"], STATUS_NOT_FOUND)


class TestAmbiguousPatternsAreReportedNotGuessed(_BaseTestCase):
    def test_two_equally_valid_learned_patterns_report_ambiguous(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{A}} is a {{B}}")
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is a ___")
        result = self.lic.understand("Python is a language")
        self.assertEqual(result.learned_pattern_match["status"], STATUS_AMBIGUOUS)
        self.assertEqual(len(result.learned_pattern_match["candidates"]), 2)


class TestOriginalMessagePreservedThroughUnderstanding(_BaseTestCase):
    def test_original_input_is_verbatim_despite_pattern_matching(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        raw = "  I love   tea  "
        result = self.lic.understand(raw)
        self.assertEqual(result.original_input, raw)


class TestLanguageMismatchDoesNotBreakPipeline(_BaseTestCase):
    """Mixed-language messages must not break the existing understanding
    pipeline (requirement 6)."""

    def test_persian_only_pattern_does_not_break_english_understanding(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        result = self.lic.understand("I love tea")
        self.assertIsNotNone(result.learned_pattern_match)
        self.assertEqual(result.learned_pattern_match["status"], STATUS_NOT_FOUND)
        # The rest of understanding is completely unaffected.
        self.assertEqual(result.original_input, "I love tea")


class TestMatchFailureIsCaughtAsAWarning(_BaseTestCase):
    """A matcher that raises must never break understanding - same
    failure-handling convention as the meaning resolver/disambiguator."""

    class _ExplodingMatcher:
        def match(self, *args, **kwargs):
            raise RuntimeError("boom")

    def test_a_raising_matcher_is_caught_and_recorded_as_a_warning(self):
        backend = DeterministicFallbackBackend(self.engine, pattern_matcher=self._ExplodingMatcher())
        lic = LanguageIntelligenceCore(backend=backend)
        result = lic.understand("I love tea")
        self.assertIsNone(result.learned_pattern_match)
        self.assertTrue(any("learned_pattern_match_error" in w for w in result.warnings))


class TestRegressionMeaningResolutionAndDisambiguationUnaffected(unittest.TestCase):
    """Regression coverage: adding pattern matching must not change
    existing Prompt 418/419/420 behaviour when a pattern_matcher is also
    configured alongside a meaning_resolver/meaning_disambiguator."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.knowledge = KnowledgeSystem(self.memory)
        self.items = LanguageLearningStore(self.memory)
        self.relationships = LanguageRelationshipStore(self.memory, self.items, self.knowledge)
        self.resolver = MeaningResolver(self.items, self.relationships, knowledge=self.knowledge)
        self.disambiguator = LearnedMeaningDisambiguator()
        self.pattern_matcher = LearnedPatternMatcher(self.items)
        self.engine = UnderstandingEngine()
        self.backend = DeterministicFallbackBackend(
            self.engine, meaning_resolver=self.resolver, meaning_disambiguator=self.disambiguator,
            pattern_matcher=self.pattern_matcher,
        )
        self.lic = LanguageIntelligenceCore(backend=self.backend)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_learned_meanings_still_populated_alongside_pattern_matching(self):
        from language_intelligence.language_learning_store import ITEM_TYPE_WORD
        self.items.learn_item("english", ITEM_TYPE_WORD, "python", meaning={"gloss": "a language"})
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{X}} is great")
        result = self.lic.understand("Python is great")
        self.assertTrue(any(e["expression"].lower() == "python" for e in result.learned_meanings))
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)

    def test_disambiguated_meanings_still_populated(self):
        from language_intelligence.language_learning_store import ITEM_TYPE_WORD
        self.items.learn_item("english", "sense_a", "bank", meaning={"gloss": "a financial institution"})
        self.items.learn_item("english", "sense_b", "bank", meaning={"gloss": "the side of a river"})
        result = self.lic.understand("The bank is closed.")
        self.assertTrue(len(result.disambiguated_meanings) >= 1)


class TestCoreIntegration(unittest.TestCase):
    """Core wires its own LearnedPatternMatcher through
    DeterministicFallbackBackend exactly like the meaning resolver."""

    def setUp(self):
        # Prompt 671: an isolated, disposable Core. A bare `Core()` resolves the
        # shipped project data/memory.db (platform default) and WRITES to it.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.core = self._new_core()

    def _new_core(self):
        core = Core(
            memory_db_path=os.path.join(self._tmpdir.name, "memory.db"),
            skill_definitions_dir=os.path.join(self._tmpdir.name, "skills"),
        )
        self.addCleanup(core.memory._conn.close)
        return core

    def test_core_has_a_pattern_matcher(self):
        core = self.core
        self.assertIsInstance(core.pattern_matcher, LearnedPatternMatcher)

    def test_core_match_learned_pattern_passthrough(self):
        core = self.core
        from language_intelligence.language_learning_store import ITEM_TYPE_PATTERN as PATTERN
        core.learn_language_item("english", PATTERN, "I love {{thing}}")
        result = core.match_learned_pattern("I love tea", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"thing": "tea"})

    def test_ordinary_conversation_populates_learned_pattern_match(self):
        core = self.core
        core.learn_language_item("english", "pattern", "I love {{thing}}")
        core.process_input("I love tea")
        self.assertIsNotNone(core.last_language_understanding)
        self.assertIsNotNone(core.last_language_understanding.learned_pattern_match)


if __name__ == "__main__":
    unittest.main()
