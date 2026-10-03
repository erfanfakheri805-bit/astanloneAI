"""
Tests for Prompt 422 - Learned Sentence Structure Extraction, integrated
into message understanding, plus Prompt 421 regression coverage.

`DeterministicFallbackBackend.understand()` (language_intelligence/
deterministic_fallback_backend.py) can optionally be given a
`LearnedSentenceStructureExtractor` (Prompt 422) next to its Prompt 421
`LearnedPatternMatcher`. When it is, the `LanguageUnderstandingResult`
it returns carries a `learned_sentence_structure` field built from the
SAME match `learned_pattern_match` reports. Nothing else on the result
changes.

Run directly:
    python -m unittest tests.test_learned_sentence_structure_in_understanding -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from memory.memory_system import MemorySystem
from language_intelligence.language_learning_store import (
    LanguageLearningStore, ITEM_TYPE_PATTERN, ITEM_TYPE_WORD,
)
from language_intelligence.meaning_resolution import MeaningResolver
from language_intelligence.learned_meaning_disambiguation import LearnedMeaningDisambiguator
from language_intelligence.learned_pattern_matching import (
    LearnedPatternMatcher, _split_template, _compile_pattern,
    STATUS_MATCHED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS, STATUS_NOT_RESOLVED,
)
from language_intelligence.learned_sentence_structure import (
    LearnedSentenceStructureExtractor, COMPONENT_FIXED, COMPONENT_VARIABLE,
    COMPONENT_UNRESOLVED,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.language_relationships import LanguageRelationshipStore

from core.core import Core


class _BaseTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + LanguageLearningStore (Prompt 416),
    the Prompt 421 matcher, the Prompt 422 extractor over it, and a
    DeterministicFallbackBackend wired to all of them - the exact
    composition Core itself builds (see core/core.py's __init__)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.items = LanguageLearningStore(self.memory)
        self.pattern_matcher = LearnedPatternMatcher(self.items)
        self.extractor = LearnedSentenceStructureExtractor(self.pattern_matcher)
        self.engine = UnderstandingEngine()
        self.backend = DeterministicFallbackBackend(
            self.engine, pattern_matcher=self.pattern_matcher,
            structure_extractor=self.extractor)
        self.lic = LanguageIntelligenceCore(backend=self.backend)

    def tearDown(self):
        self._tmpdir.cleanup()


class TestStructureIsExposedDuringUnderstanding(_BaseTestCase):
    """11. Understanding Engine integration."""

    def test_matching_persian_message_exposes_its_structure(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                               meaning={"intent": "likes_thing"})
        result = self.lic.understand("من کتاب را دوست دارم")
        structure = result.learned_sentence_structure
        self.assertIsNotNone(structure)
        self.assertEqual(structure["status"], STATUS_MATCHED)
        self.assertEqual(
            [c["kind"] for c in structure["components"]],
            [COMPONENT_FIXED, COMPONENT_VARIABLE, COMPONENT_FIXED],
        )
        variable = structure["components"][1]
        self.assertEqual((variable["variable_name"], variable["value"]), ("X", "کتاب"))
        self.assertEqual(structure["meaning"], {"intent": "likes_thing"})

    def test_two_variables_stay_separate_through_understanding(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را به {{Y}} می‌دهم")
        result = self.lic.understand("من کتاب را به علی می‌دهم")
        values = {c["variable_name"]: c["value"]
                  for c in result.learned_sentence_structure["components"]
                  if c["kind"] == COMPONENT_VARIABLE}
        self.assertEqual(values, {"X": "کتاب", "Y": "علی"})

    def test_structure_is_built_from_the_same_match_the_result_reports(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                               meaning={"intent": "likes_thing"}, confidence=0.7, source="taught")
        result = self.lic.understand("من کتاب را دوست دارم")
        match = result.learned_pattern_match
        structure = result.learned_sentence_structure
        self.assertEqual(structure["matched_pattern_id"], match["matched_pattern_id"])
        self.assertEqual(structure["matched_pattern_text"], match["matched_pattern_text"])
        self.assertEqual(structure["meaning"], match["meaning"])
        self.assertEqual(structure["confidence"], match["confidence"])
        self.assertEqual(structure["source"], match["source"])
        self.assertEqual(structure["language"], match["language"])
        values = {c["variable_name"]: c["value"] for c in structure["components"]
                  if c["kind"] == COMPONENT_VARIABLE}
        self.assertEqual(values, match["variables"])

    def test_the_message_is_matched_once_not_twice(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        calls = []

        class _CountingMatcher(LearnedPatternMatcher):
            def match(self, *args, **kwargs):
                calls.append(1)
                return super().match(*args, **kwargs)

        matcher = _CountingMatcher(self.items)
        backend = DeterministicFallbackBackend(
            self.engine, pattern_matcher=matcher,
            structure_extractor=LearnedSentenceStructureExtractor(matcher))
        LanguageIntelligenceCore(backend=backend).understand("من کتاب را دوست دارم")
        self.assertEqual(len(calls), 1)

    def test_result_carries_the_new_field_in_to_dict_and_is_json_safe(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        result = self.lic.understand("من کتاب را دوست دارم")
        as_dict = result.to_dict()
        self.assertIn("learned_sentence_structure", as_dict)
        self.assertEqual(as_dict["learned_sentence_structure"]["status"], STATUS_MATCHED)
        json.dumps(as_dict, ensure_ascii=False)

    def test_isinstance_check(self):
        result = self.lic.understand("من کتاب را دوست دارم")
        self.assertIsInstance(result, LanguageUnderstandingResult)

    def test_unmatched_message_has_a_not_found_structure_with_no_components(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.lic.understand("I hate broccoli")
        structure = result.learned_sentence_structure
        self.assertEqual(structure["status"], STATUS_NOT_FOUND)
        self.assertEqual(structure["components"], [])
        self.assertIsNone(structure["meaning"])

    def test_ambiguous_message_reports_ambiguous_structure_without_choosing(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{A}} is a {{B}}",
                               meaning={"intent": "classify"})
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is a ___",
                               meaning={"intent": "define"})
        result = self.lic.understand("Python is a language")
        structure = result.learned_sentence_structure
        self.assertEqual(structure["status"], STATUS_AMBIGUOUS)
        self.assertEqual(structure["components"], [])
        self.assertEqual(len(structure["candidates"]), 2)
        self.assertIsNone(structure["meaning"])

    def test_unresolved_run_is_preserved_through_understanding(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "{{A}} {{B}} خوب است")
        result = self.lic.understand("سیب سرخ خوب است")
        structure = result.learned_sentence_structure
        self.assertEqual(structure["status"], STATUS_NOT_RESOLVED)
        self.assertEqual(structure["components"][0]["kind"], COMPONENT_UNRESOLVED)
        self.assertEqual(structure["components"][0]["text"], "سیب سرخ")
        self.assertIsNone(structure["components"][0]["value"])

    def test_language_mismatch_yields_no_structure(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "I love {{thing}}")
        # An English message must not be structured by a Persian pattern.
        result = self.lic.understand("I love tea")
        self.assertEqual(result.learned_sentence_structure["status"], STATUS_NOT_FOUND)
        self.assertEqual(result.learned_sentence_structure["components"], [])


class TestOriginalMessagePreservedThroughUnderstanding(_BaseTestCase):
    """9. Original message preservation."""

    def test_structure_original_message_is_the_untouched_user_input(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        raw = "  من   کتاب را   دوست دارم  "
        result = self.lic.understand(raw)
        structure = result.learned_sentence_structure
        self.assertEqual(result.original_input, raw)
        self.assertEqual(structure["original_message"], raw)
        self.assertEqual(structure["normalized_message"], result.normalized_input)
        for component in structure["components"]:
            self.assertEqual(
                structure["normalized_message"][component["start"]:component["end"]],
                component["text"],
            )

    def test_original_message_is_kept_for_non_matching_input(self):
        raw = "  چیز دیگری  "
        result = self.lic.understand(raw)
        self.assertEqual(result.learned_sentence_structure["original_message"], raw)


class TestNothingElseOnTheResultChanges(unittest.TestCase):
    """11. Preserve every existing piece of the Understanding result -
    original message, learned meanings, disambiguation, references,
    active topic, context."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.items = LanguageLearningStore(self.memory)
        self.relationships = LanguageRelationshipStore(self.memory, self.items)
        self.resolver = MeaningResolver(self.items, self.relationships)
        self.disambiguator = LearnedMeaningDisambiguator()
        self.pattern_matcher = LearnedPatternMatcher(self.items)
        self.extractor = LearnedSentenceStructureExtractor(self.pattern_matcher)
        self.engine = UnderstandingEngine()

        def backend(with_extractor):
            return DeterministicFallbackBackend(
                self.engine, meaning_resolver=self.resolver,
                meaning_disambiguator=self.disambiguator, pattern_matcher=self.pattern_matcher,
                structure_extractor=self.extractor if with_extractor else None)

        self.without = LanguageIntelligenceCore(backend=backend(False))
        self.with_structure = LanguageIntelligenceCore(backend=backend(True))

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_every_other_field_is_identical_with_and_without_the_extractor(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python",
                               meaning={"gloss": "a programming language"})
        self.items.learn_item("english", "sense_a", "bank", meaning={"gloss": "a financial institution"})
        self.items.learn_item("english", "sense_b", "bank", meaning={"gloss": "a river side"})
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{X}} is great",
                               meaning={"intent": "praise"})
        for message in ("Python is great", "The bank is closed.", "hello", ""):
            before = self.without.understand(message).to_dict()
            after = self.with_structure.understand(message).to_dict()
            structure = after.pop("learned_sentence_structure")
            before_structure = before.pop("learned_sentence_structure")
            self.assertIsNone(before_structure)
            self.assertEqual(after, before, message)
            if message:
                self.assertIsNotNone(structure)

    def test_learned_meanings_and_pattern_match_survive_alongside_structure(self):
        self.items.learn_item("english", ITEM_TYPE_WORD, "python",
                               meaning={"gloss": "a programming language"})
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{X}} is great")
        result = self.with_structure.understand("Python is great")
        self.assertTrue(any(e["expression"].lower() == "python" for e in result.learned_meanings))
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)
        self.assertEqual(result.learned_sentence_structure["status"], STATUS_MATCHED)
        self.assertEqual(result.original_input, "Python is great")
        self.assertIsNotNone(result.language_context)

    def test_context_fields_pass_through_when_supplied(self):
        class _Dictable:
            def __init__(self, payload):
                self.payload = payload

            def to_dict(self):
                return dict(self.payload)

        topic = _Dictable({"topic": "tea"})
        relevant = _Dictable({"turns": []})
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.with_structure.understand(
            "I love tea", relevant_context=relevant, active_topic=topic)
        self.assertEqual(result.active_topic, {"topic": "tea"})
        self.assertEqual(result.conversation_context, {"turns": []})
        self.assertEqual(result.learned_sentence_structure["status"], STATUS_MATCHED)


class TestDefaultsAndFailureHandling(_BaseTestCase):
    def test_no_extractor_reproduces_the_pre_422_shape(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        backend = DeterministicFallbackBackend(self.engine, pattern_matcher=self.pattern_matcher)
        result = LanguageIntelligenceCore(backend=backend).understand("I love tea")
        self.assertIsNone(result.learned_sentence_structure)
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)
        self.assertIn("learned_sentence_structure", result.to_dict())
        self.assertIsNone(result.to_dict()["learned_sentence_structure"])

    def test_extractor_without_matcher_yields_no_structure(self):
        backend = DeterministicFallbackBackend(self.engine, structure_extractor=self.extractor)
        result = LanguageIntelligenceCore(backend=backend).understand("I love tea")
        self.assertIsNone(result.learned_pattern_match)
        self.assertIsNone(result.learned_sentence_structure)

    def test_extractor_failure_is_a_warning_and_keeps_the_match(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")

        class _Broken:
            def from_match(self, *args, **kwargs):
                raise RuntimeError("boom")

        backend = DeterministicFallbackBackend(
            self.engine, pattern_matcher=self.pattern_matcher, structure_extractor=_Broken())
        result = LanguageIntelligenceCore(backend=backend).understand("I love tea")
        self.assertIsNone(result.learned_sentence_structure)
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)
        self.assertTrue(any(w.startswith("learned_sentence_structure_error")
                            for w in result.warnings))
        self.assertEqual(result.original_input, "I love tea")

    def test_understanding_writes_nothing_to_the_learning_store(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        before = self.items.items_for_language("persian")
        self.lic.understand("من کتاب را دوست دارم")
        self.assertEqual(self.items.items_for_language("persian"), before)


class TestCoreIntegration(unittest.TestCase):
    """Core wires its own extractor over its own matcher."""

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

    def test_core_has_an_extractor_over_its_own_matcher(self):
        core = self.core
        self.assertIsInstance(core.sentence_structure_extractor, LearnedSentenceStructureExtractor)
        self.assertIs(core.sentence_structure_extractor.pattern_matcher, core.pattern_matcher)

    def test_core_extract_sentence_structure_passthrough(self):
        core = self.core
        core.learn_language_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را به {{Y}} می‌دهم",
                                 meaning={"intent": "give"})
        result = core.extract_sentence_structure("من کتاب را به علی می‌دهم", language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(result.meaning, {"intent": "give"})

    def test_ordinary_conversation_populates_the_structure(self):
        core = self.core
        core.learn_language_item("english", "pattern", "I love {{thing}}")
        core.process_input("I love tea")
        understanding = core.last_language_understanding
        self.assertIsNotNone(understanding)
        self.assertIsNotNone(understanding.learned_sentence_structure)
        self.assertEqual(understanding.learned_sentence_structure["status"], STATUS_MATCHED)
        self.assertEqual(understanding.learned_sentence_structure["components"][1]["value"], "tea")

    def test_persian_conversation_populates_the_structure(self):
        core = self.core
        core.learn_language_item("persian", "pattern", "من {{X}} را دوست دارم")
        core.process_input("من کتاب را دوست دارم")
        structure = core.last_language_understanding.learned_sentence_structure
        self.assertEqual(structure["status"], STATUS_MATCHED)
        self.assertEqual(structure["components"][1]["value"], "کتاب")


class TestPrompt421Regression(_BaseTestCase):
    """12. Prompt 421 pattern recognition is unchanged."""

    def test_compiled_regex_for_a_multi_variable_pattern_is_unchanged(self):
        regex, names, indeterminate = _compile_pattern(
            _split_template("من {{X}} را به {{Y}} می‌دهم"))
        self.assertEqual(
            regex.pattern,
            r"^\s*من\s+(\S.*?|\S)\s+را\s+به\s+(\S.*?|\S)\s+می‌دهم\s*$",
        )
        self.assertEqual(names, ["X", "Y"])
        self.assertFalse(indeterminate)

    def test_adjacent_variables_are_still_flagged_indeterminate(self):
        _, names, indeterminate = _compile_pattern(_split_template("{{A}} {{B}} خوب است"))
        self.assertEqual(names, ["A", "B"])
        self.assertTrue(indeterminate)

    def test_matcher_results_are_unchanged(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را به {{Y}} می‌دهم",
                               meaning={"intent": "give"})
        result = self.pattern_matcher.match("من کتاب را به علی می‌دهم", language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(result.meaning, {"intent": "give"})
        self.assertEqual(
            set(result.to_dict()),
            {"original_message", "status", "matched", "matched_pattern_id",
             "matched_pattern_text", "variables", "meaning", "language", "locale",
             "confidence", "source", "candidates", "reason", "truncated", "limits"},
        )

    def test_understanding_still_reports_the_421_match_field(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}",
                               meaning={"intent": "likes_thing"})
        result = self.lic.understand("I love tea")
        self.assertEqual(result.learned_pattern_match["status"], STATUS_MATCHED)
        self.assertEqual(result.learned_pattern_match["variables"], {"thing": "tea"})
        self.assertEqual(result.learned_pattern_match["meaning"], {"intent": "likes_thing"})
        expected = self.pattern_matcher.match(result.normalized_input, language="english")
        self.assertEqual(result.learned_pattern_match["matched_pattern_id"],
                         expected.matched_pattern_id)


if __name__ == "__main__":
    unittest.main()
