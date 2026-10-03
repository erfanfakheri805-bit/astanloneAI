"""
Tests for Prompt 434 - Learned Response Pattern Selection.

`LearnedResponsePatternSelector` (language_intelligence/
learned_response_pattern_selection.py) deterministically selects the one
already-taught learned response pattern that applies to the language
information the response-generation path already has (resolved learned
meaning, learned expressions, learned sentence patterns, recognized
sentence structure, language, locale, active topic, resolved references,
conversation context) - or reports AMBIGUOUS (several equally valid,
all preserved) or NOT_FOUND (nothing invented). Its result is carried by
`ResponseGenerationContext.response_pattern_selection` and, from there,
`BackendGenerationRequest.response_pattern_selection`.

Unit-level tests hand-build the plan dict the selector reads (the exact
shape `ResponsePlan.to_dict()` produces), so each rule is exercised on
its own. Integration-level tests drive a real Understanding Engine and
real Prompt 416-424 stores, teach response patterns through the EXISTING
teaching/binding operations (the open stored `meaning` value), and read
the selection off the real `ResponseGenerationContext` /
`ResponseGenerationRequest`.

Run directly:
    python -m unittest tests.test_learned_response_pattern_selection -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import LanguageRelationshipStore
from language_intelligence.meaning_resolution import MeaningResolver
from language_intelligence.learned_meaning_disambiguation import LearnedMeaningDisambiguator
from language_intelligence.learned_pattern_matching import LearnedPatternMatcher
from language_intelligence.learned_sentence_structure import LearnedSentenceStructureExtractor
from language_intelligence.learned_pattern_teaching import LearnedPatternTeacher, STATUS_CREATED
from language_intelligence.learned_pattern_meaning import LearnedPatternMeaningBinder
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_planning import (
    ResponsePlanner, ResponsePlan, STATUS_RESOLVED as PLAN_RESOLVED,
    STATUS_AMBIGUOUS as PLAN_AMBIGUOUS, STATUS_UNRESOLVED as PLAN_UNRESOLVED,
)
from language_intelligence.language_guidance import (
    LearnedLanguageGuidance, build_language_guidance, language_guidance_from_understanding,
)
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.response_generation import (
    ResponseGenerationRequest, STATUS_DEFERRED,
)
from language_intelligence.learned_response_pattern_selection import (
    LearnedResponsePatternSelector, LearnedResponsePatternSelection,
    select_learned_response_pattern, response_pattern_selection_from_understanding,
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND, ALL_STATUSES,
    REASON_UNIQUE_BEST_MATCH, REASON_EQUALLY_VALID, REASON_UNDECIDED_UNDERSTANDING,
    REASON_NONE_AVAILABLE, REASON_NONE_ELIGIBLE, RESPONSE_PATTERNS_KEY,
    ORIGIN_MEANING, ORIGIN_SENTENCE_PATTERN, ORIGIN_EXPRESSION, ORIGIN_UNDECIDED_MEANING,
    MAX_PATTERNS_PER_SOURCE, MAX_CANDIDATES,
)

from core.core import Core

QUESTION_PATTERN = "what is {{topic}}"
GREETING_PATTERN = "good morning"
PREFERENCE_PATTERN = "من {{X}} را دوست دارم"


# ----------------------------------------------------------------------
# Hand-built plan dicts (the shape `ResponsePlan.to_dict()` produces)
# ----------------------------------------------------------------------
def _meaning(name="greeting", patterns=None, **extra):
    """A Prompt 424 bound-meaning candidate dict whose stored value
    carries `patterns` under `response_patterns`."""
    stored = {} if patterns is None else {RESPONSE_PATTERNS_KEY: patterns}
    meaning = {
        "id": 1, "meaning_id": 1, "key": name, "meaning_name": name, "item_type": "meaning",
        "language": "english", "locale": None, "meaning": stored, "confidence": 0.9,
        "source": "unit-test", "related": [],
    }
    meaning.update(extra)
    return meaning


def _pattern(patterns=None, pattern_id=7, text="what is {{topic}}", **extra):
    """A `ResponsePlan.matched_pattern` dict whose stored value carries
    `patterns` under `response_patterns`."""
    stored = {} if patterns is None else {RESPONSE_PATTERNS_KEY: patterns}
    matched = {
        "pattern_id": pattern_id, "pattern_text": text, "language": "english", "locale": None,
        "confidence": 0.8, "source": "pattern-source", "meaning": stored,
    }
    matched.update(extra)
    return matched


def _expression(expression, patterns=None, status="RESOLVED", **extra):
    stored = {} if patterns is None else {RESPONSE_PATTERNS_KEY: patterns}
    resolved = {"id": 5, "key": expression, "meaning": stored, "confidence": 0.7,
                "source": "expression-source"}
    resolved.update(extra)
    return {"expression": expression, "status": status, "resolved_meaning": resolved,
            "candidates": [], "reason": None}


def _plan(meaning=None, meaning_candidates=None, matched_pattern=None, language="english",
          locale=None, active_topic=None, references=None, context=None,
          expression_meanings=None, variables=None, status=None):
    if status is None:
        if meaning is not None:
            status = PLAN_RESOLVED
        elif meaning_candidates:
            status = PLAN_AMBIGUOUS
        else:
            status = PLAN_UNRESOLVED
    return {
        "original_message": "hello", "detected_language": language, "locale": locale,
        "status": status, "meaning": meaning, "meaning_candidates": meaning_candidates or [],
        "matched_pattern": matched_pattern, "variables": variables or {},
        "expression_meanings": expression_meanings or [], "active_topic": active_topic,
        "references": references or [], "context": context, "response_action": None,
        "unresolved_requirements": [],
    }


def _ids(selection_dict):
    return [c["pattern_id"] for c in selection_dict["candidates"]]


def _select(plan, guidance=None):
    return LearnedResponsePatternSelector().select(plan, guidance)


# ----------------------------------------------------------------------
class _PipelineCase(unittest.TestCase):
    """A real Understanding Engine + real Prompt 416-424 stores wired to
    a LanguageIntelligenceCore, as test_language_guidance.py's _PlanCase
    builds them. Response patterns are taught through the EXISTING
    operations: `learn_item(..., meaning={...})` for a meaning,
    `teach(..., meaning={...})` for a sentence pattern."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.memory = MemorySystem(os.path.join(self._tmpdir.name, "memory.db"))
        self.items = LanguageLearningStore(self.memory)
        self.knowledge = KnowledgeSystem(self.memory)
        self.rels = LanguageRelationshipStore(self.memory, self.items, self.knowledge)
        self.resolver = MeaningResolver(self.items, self.rels, knowledge=self.knowledge)
        self.disambiguator = LearnedMeaningDisambiguator()
        self.matcher = LearnedPatternMatcher(self.items)
        self.extractor = LearnedSentenceStructureExtractor(self.matcher)
        self.teacher = LearnedPatternTeacher(self.items)
        self.binder = LearnedPatternMeaningBinder(self.items, self.rels, self.disambiguator)
        self.backend = DeterministicFallbackBackend(
            UnderstandingEngine(), meaning_resolver=self.resolver,
            meaning_disambiguator=self.disambiguator, pattern_matcher=self.matcher,
            structure_extractor=self.extractor, pattern_meaning_binder=self.binder)
        self.planner = ResponsePlanner()
        self.lic = LanguageIntelligenceCore(backend=self.backend, response_planner=self.planner)

    def teach(self, pattern, language="en", **kwargs):
        result = self.teacher.teach(language, pattern, **kwargs)
        self.assertEqual(result.status, STATUS_CREATED, result.errors)
        return result

    def bind(self, pattern, meaning, language="en", **kwargs):
        result = self.binder.bind(language, pattern, meaning, **kwargs)
        self.assertTrue(result.success, result.errors)
        return result

    def teach_meaning(self, name, patterns, language="en", **extra):
        value = {RESPONSE_PATTERNS_KEY: patterns}
        value.update(extra)
        return self.items.learn_item(language, "meaning", name, meaning=value)

    def understand(self, text, **context):
        return self.lic.understand(text, **context)


# ----------------------------------------------------------------------
class TestUniqueMatchingResponsePattern(unittest.TestCase):
    """1. A unique matching learned response pattern is selected."""

    def test_the_only_taught_pattern_of_a_resolved_meaning_is_selected(self):
        taught = {"id": "greet_back", "template": "Good morning!"}
        result = _select(_plan(meaning=_meaning(patterns=[taught]))).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["reason"], REASON_UNIQUE_BEST_MATCH)
        self.assertEqual(result["selected_pattern"]["pattern_id"], "greet_back")
        self.assertEqual(result["candidates"], [])

    def test_the_selected_pattern_is_returned_exactly_as_taught(self):
        taught = {"id": "greet_back", "template": "Good morning, {{X}}!", "extra": [1, {"a": 2}]}
        result = _select(_plan(meaning=_meaning(patterns=[taught]))).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern"], taught)

    def test_the_result_reports_where_the_pattern_came_from(self):
        result = _select(_plan(meaning=_meaning("greeting", [{"id": "g"}]))).to_dict()
        self.assertEqual(result["selected_pattern"]["origin"],
                         {"kind": ORIGIN_MEANING, "id": 1, "name": "greeting"})

    def test_a_unique_pattern_on_the_matched_sentence_pattern_is_selected(self):
        plan = _plan(matched_pattern=_pattern([{"id": "on_sentence_pattern"}]))
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["selected_pattern"]["origin"]["kind"], ORIGIN_SENTENCE_PATTERN)

    def test_a_unique_pattern_on_a_resolved_expression_meaning_is_selected(self):
        plan = _plan(expression_meanings=[_expression("python", [{"id": "on_expression"}])])
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["selected_pattern"]["origin"]["kind"], ORIGIN_EXPRESSION)
        self.assertEqual(result["selected_pattern"]["origin"]["name"], "python")

    def test_the_stronger_candidate_wins_over_a_generic_one(self):
        patterns = [{"id": "generic"}, {"id": "topical", "topic": "python"}]
        plan = _plan(meaning=_meaning(patterns=patterns), active_topic={"topic": "python"})
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["selected_pattern"]["pattern_id"], "topical")
        self.assertEqual(result["selected_pattern"]["matched_on"], ["topic"])

    def test_confidence_and_source_are_the_patterns_own_when_taught(self):
        taught = {"id": "g", "confidence": 0.4, "source": "teacher"}
        result = _select(_plan(meaning=_meaning(patterns=[taught]))).to_dict()
        self.assertAlmostEqual(result["confidence"], 0.4)
        self.assertEqual(result["source"], "teacher")

    def test_confidence_and_source_fall_back_to_the_carrying_item(self):
        result = _select(_plan(meaning=_meaning(patterns=[{"id": "g"}]))).to_dict()
        self.assertAlmostEqual(result["confidence"], 0.9)
        self.assertEqual(result["source"], "unit-test")

    def test_the_result_is_a_selection_object_and_json_shaped(self):
        selection = _select(_plan(meaning=_meaning(patterns=[{"id": "g"}])))
        self.assertIsInstance(selection, LearnedResponsePatternSelection)
        self.assertTrue(selection.resolved)
        json.dumps(selection.to_dict(), ensure_ascii=False)
        self.assertIn(selection.status, ALL_STATUSES)


# ----------------------------------------------------------------------
class TestNoMatchingResponsePattern(unittest.TestCase):
    """2. No suitable learned response pattern -> NOT_FOUND."""

    def test_nothing_taught_is_not_found(self):
        result = _select(_plan(meaning=_meaning(patterns=None))).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["reason"], REASON_NONE_AVAILABLE)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["confidence"])
        self.assertIsNone(result["source"])

    def test_an_empty_plan_is_not_found(self):
        result = _select(_plan()).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["reason"], REASON_NONE_AVAILABLE)

    def test_taught_patterns_none_of_which_apply_are_not_found(self):
        patterns = [{"id": "a", "locale": "en-GB"}, {"id": "b", "topic": "cooking"}]
        result = _select(_plan(meaning=_meaning(patterns=patterns), locale="en-US")).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["reason"], REASON_NONE_ELIGIBLE)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(result["candidates"], [])

    def test_language_and_locale_are_still_reported_when_not_found(self):
        result = _select(_plan(language="persian", locale="fa-IR")).to_dict()
        self.assertEqual(result["language"], "persian")
        self.assertEqual(result["locale"], "fa-IR")

    def test_a_malformed_response_patterns_value_is_not_found(self):
        for value in ("not a list", 5, {"id": "x"}, [None, 3, "s", []]):
            meaning = _meaning()
            meaning["meaning"] = {RESPONSE_PATTERNS_KEY: value}
            with self.subTest(value=value):
                result = _select(_plan(meaning=meaning)).to_dict()
                self.assertEqual(result["status"], STATUS_NOT_FOUND)

    def test_a_stored_value_that_is_not_an_object_is_not_found(self):
        for stored in (None, "text", 4, [{"id": "x"}]):
            meaning = _meaning()
            meaning["meaning"] = stored
            with self.subTest(stored=stored):
                self.assertEqual(_select(_plan(meaning=meaning)).status, STATUS_NOT_FOUND)


# ----------------------------------------------------------------------
class TestMultipleEquallyValidCandidates(unittest.TestCase):
    """3. Equally valid candidates -> AMBIGUOUS, none picked."""

    def test_two_unconditioned_patterns_are_ambiguous(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "first"}, {"id": "second"}]))
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(result["reason"], REASON_EQUALLY_VALID)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(_ids(result), ["first", "second"])
        self.assertIsNone(result["confidence"])

    def test_candidates_keep_the_order_they_were_taught_in(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "z"}, {"id": "a"}, {"id": "m"}]))
        self.assertEqual(_ids(_select(plan).to_dict()), ["z", "a", "m"])

    def test_equally_strong_candidates_from_different_sources_are_ambiguous(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "from_meaning", "language": "en"}]),
                     matched_pattern=_pattern([{"id": "from_pattern", "language": "en"}]))
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(_ids(result), ["from_meaning", "from_pattern"])

    def test_only_the_equally_strongest_candidates_are_kept(self):
        patterns = [{"id": "generic"}, {"id": "a", "language": "en"}, {"id": "b", "language": "en"}]
        result = _select(_plan(meaning=_meaning(patterns=patterns))).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(_ids(result), ["a", "b"])

    def test_every_candidate_carries_its_pattern_origin_and_evidence(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "a", "template": "A"},
                                                {"id": "b", "template": "B"}]))
        candidates = _select(plan).to_dict()["candidates"]
        self.assertEqual([c["pattern"]["template"] for c in candidates], ["A", "B"])
        for candidate in candidates:
            self.assertEqual(candidate["origin"]["kind"], ORIGIN_MEANING)
            self.assertEqual(candidate["matched_on"], [])
            self.assertAlmostEqual(candidate["confidence"], 0.9)

    def test_identical_duplicates_are_one_candidate_not_an_ambiguity(self):
        same = {"id": "same", "template": "T"}
        plan = _plan(meaning=_meaning(patterns=[copy.deepcopy(same)]),
                     matched_pattern=_pattern([copy.deepcopy(same)]))
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["selected_pattern"]["origin"]["kind"], ORIGIN_MEANING)

    def test_the_same_id_with_different_content_is_still_ambiguous(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "x", "template": "1"}]),
                     matched_pattern=_pattern([{"id": "x", "template": "2"}]))
        self.assertEqual(_select(plan).status, STATUS_AMBIGUOUS)


# ----------------------------------------------------------------------
class TestLanguageFiltering(unittest.TestCase):
    """4. A pattern that declares a language applies only in that language."""

    def test_a_pattern_for_the_contexts_language_is_selected(self):
        patterns = [{"id": "fa_pattern", "language": "fa"}, {"id": "en_pattern", "language": "en"}]
        result = _select(_plan(meaning=_meaning(patterns=patterns), language="persian")).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "fa_pattern")
        result = _select(_plan(meaning=_meaning(patterns=patterns), language="english")).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "en_pattern")

    def test_language_codes_and_names_agree(self):
        for declared in ("en", "EN", "english", "English", "en-US", "en_GB"):
            with self.subTest(declared=declared):
                plan = _plan(meaning=_meaning(patterns=[{"id": "p", "language": declared}]))
                self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_a_pattern_for_another_language_is_excluded(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "fa_only", "language": "fa"}]))
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["reason"], REASON_NONE_ELIGIBLE)

    def test_a_pattern_declaring_a_language_needs_the_context_to_know_one(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "language": "en"}]), language=None)
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_pattern_declaring_no_language_applies_in_any_language(self):
        for language in ("english", "persian", "fi", None):
            with self.subTest(language=language):
                plan = _plan(meaning=_meaning(patterns=[{"id": "any"}]), language=language)
                self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_a_malformed_language_is_never_satisfied(self):
        for declared in (5, ["en"], "", "unknown", True):
            with self.subTest(declared=declared):
                plan = _plan(meaning=_meaning(patterns=[{"id": "p", "language": declared}]))
                self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_the_reported_language_is_the_contexts_own(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "language": "fa"}]), language="persian")
        self.assertEqual(_select(plan).to_dict()["language"], "persian")


# ----------------------------------------------------------------------
class TestLocaleFiltering(unittest.TestCase):
    """5. A pattern that declares a locale applies only under that locale."""

    def test_a_pattern_for_the_contexts_locale_is_selected(self):
        patterns = [{"id": "gb", "locale": "en-GB"}, {"id": "us", "locale": "en-US"}]
        result = _select(_plan(meaning=_meaning(patterns=patterns), locale="en-GB")).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "gb")
        self.assertEqual(result["locale"], "en-GB")

    def test_a_pattern_for_another_locale_is_excluded(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "us", "locale": "en-US"}]), locale="en-GB")
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_locale_pattern_needs_the_context_to_state_a_locale(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "us", "locale": "en-US"}]), locale=None)
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_locale_agnostic_pattern_applies_under_any_locale(self):
        for locale in ("en-GB", "fa-IR", None):
            with self.subTest(locale=locale):
                plan = _plan(meaning=_meaning(patterns=[{"id": "any"}]), locale=locale)
                self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_locale_comparison_ignores_case_and_underscore(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "locale": "fa_ir"}]), locale="fa-IR")
        self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_a_locale_specific_pattern_beats_a_locale_agnostic_one(self):
        patterns = [{"id": "any"}, {"id": "gb", "locale": "en-GB"}]
        result = _select(_plan(meaning=_meaning(patterns=patterns), locale="en-GB")).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "gb")

    def test_language_and_locale_must_both_hold(self):
        patterns = [{"id": "p", "language": "en", "locale": "en-GB"}]
        self.assertEqual(
            _select(_plan(meaning=_meaning(patterns=patterns), locale="en-GB")).status,
            STATUS_RESOLVED)
        self.assertEqual(
            _select(_plan(meaning=_meaning(patterns=patterns), locale="en-GB",
                          language="persian")).status, STATUS_NOT_FOUND)


# ----------------------------------------------------------------------
class TestMeaningMatching(unittest.TestCase):
    """6. A pattern that declares a meaning applies only under that
    RESOLVED learned meaning."""

    def test_a_pattern_for_the_resolved_meaning_is_selected(self):
        patterns = [{"id": "for_greeting", "meaning": "greeting"},
                    {"id": "for_question", "meaning": "ask_question"}]
        plan = _plan(meaning=_meaning("greeting", patterns))
        result = _select(plan).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "for_greeting")
        self.assertEqual(result["selected_pattern"]["matched_on"], ["meaning"])

    def test_meaning_names_compare_like_the_planner_compares_them(self):
        plan = _plan(meaning=_meaning("ask_question", [{"id": "p", "meaning": "Ask Question"}]))
        self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_a_pattern_for_another_meaning_is_excluded(self):
        plan = _plan(meaning=_meaning("greeting", [{"id": "p", "meaning": "farewell"}]))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_meaning_pattern_needs_a_resolved_meaning(self):
        plan = _plan(matched_pattern=_pattern([{"id": "p", "meaning": "greeting"}]))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_pattern_taught_on_a_sentence_pattern_can_still_require_a_meaning(self):
        plan = _plan(meaning=_meaning("greeting"),
                     matched_pattern=_pattern([{"id": "p", "meaning": "greeting"}]))
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["selected_pattern"]["origin"]["kind"], ORIGIN_SENTENCE_PATTERN)

    def test_an_undecided_meaning_never_satisfies_a_meaning_condition(self):
        candidates = [_meaning("a", [{"id": "pa", "meaning": "a"}]),
                      _meaning("b", [{"id": "pb", "meaning": "b"}], meaning_id=2)]
        result = _select(_plan(meaning_candidates=candidates)).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)


# ----------------------------------------------------------------------
class TestSentencePatternMatching(unittest.TestCase):
    """7. Patterns tied to the recognized learned sentence pattern /
    structure."""

    def test_a_pattern_declaring_the_matched_sentence_pattern_by_id(self):
        patterns = [{"id": "hit", "sentence_pattern": 7}, {"id": "miss", "sentence_pattern": 8}]
        result = _select(_plan(matched_pattern=_pattern(patterns, pattern_id=7))).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "hit")
        self.assertEqual(result["selected_pattern"]["matched_on"], ["sentence_pattern"])

    def test_a_pattern_declaring_the_matched_sentence_pattern_by_text(self):
        patterns = [{"id": "hit", "sentence_pattern": "what  is {{topic}}"}]
        result = _select(_plan(matched_pattern=_pattern(patterns))).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)

    def test_a_pattern_for_another_sentence_pattern_is_excluded(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "sentence_pattern": "who is {{x}}"}]),
                     matched_pattern=_pattern(None))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_sentence_pattern_condition_needs_a_matched_pattern(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "sentence_pattern": 7}]))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_boolean_is_not_a_pattern_id(self):
        plan = _plan(matched_pattern=_pattern([{"id": "p", "sentence_pattern": True}],
                                              pattern_id=1))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_variables_named_by_a_pattern_must_have_extracted_values(self):
        patterns = [{"id": "needs_topic", "variables": ["topic"]},
                    {"id": "needs_other", "variables": ["other"]}]
        plan = _plan(matched_pattern=_pattern(patterns), variables={"topic": "python"})
        result = _select(plan).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "needs_topic")
        self.assertEqual(result["selected_pattern"]["matched_on"], ["variables"])

    def test_a_variable_without_an_extracted_value_does_not_count(self):
        plan = _plan(matched_pattern=_pattern([{"id": "p", "variables": ["topic"]}]),
                     variables={"topic": None})
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_variables_are_also_read_from_the_recognized_structure(self):
        structure = {
            "status": "MATCHED",
            "components": [
                {"kind": "fixed", "text": "what is", "variable_name": None, "value": None},
                {"kind": "variable", "text": "python", "variable_name": "topic",
                 "value": "python"},
            ],
        }
        plan = _plan(matched_pattern=_pattern([{"id": "p", "variables": ["topic"]}]))
        guidance = build_language_guidance(plan, sentence_structure=structure)
        self.assertEqual(_select(plan, guidance).status, STATUS_RESOLVED)

    def test_an_unresolved_structure_contributes_no_variables(self):
        structure = {
            "status": "NOT_RESOLVED",
            "components": [{"kind": "variable", "text": "a b", "variable_name": "topic",
                            "value": "a b"}],
        }
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "variables": ["topic"]}]))
        guidance = build_language_guidance(plan, sentence_structure=structure)
        self.assertEqual(_select(plan, guidance).status, STATUS_NOT_FOUND)

    def test_malformed_variable_conditions_are_never_satisfied(self):
        for declared in ("topic", [], [5], [""], {"topic": 1}):
            with self.subTest(declared=declared):
                plan = _plan(matched_pattern=_pattern([{"id": "p", "variables": declared}]),
                             variables={"topic": "x"})
                self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)


# ----------------------------------------------------------------------
class TestTopicAndContextRelevance(unittest.TestCase):
    """8. Active topic / conversation context relevance."""

    def test_a_pattern_for_the_active_topic_is_selected(self):
        patterns = [{"id": "python_topic", "topic": "python"},
                    {"id": "cooking_topic", "topic": "cooking"}]
        plan = _plan(meaning=_meaning(patterns=patterns), active_topic={"topic": "python"})
        result = _select(plan).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "python_topic")

    def test_topic_comparison_ignores_case_and_spacing(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": "Machine  Learning"}]),
                     active_topic={"topic": "machine learning"})
        self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_a_topic_pattern_needs_a_known_topic(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": "python"}]))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_pattern_for_a_different_topic_is_excluded(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": "python"}]),
                     active_topic={"topic": "cooking"})
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_the_conversation_contexts_topic_is_used_when_no_active_topic(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": "python"}]),
                     context={"topic": {"topic": "python"}})
        self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_the_active_topic_takes_precedence_over_the_conversation_context(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": "python"}]),
                     active_topic={"topic": "cooking"}, context={"topic": {"topic": "python"}})
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_topic_free_pattern_still_applies_when_a_topic_is_active(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "any"}]), active_topic={"topic": "x"})
        self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_conversation_context_is_never_scanned_for_anything_else(self):
        context = {"topic": None, "background_topics": [{"topic": "python", "terms": ["python"]}],
                   "preferences": [{"text": "python"}]}
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": "python"}]), context=context)
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_malformed_topic_is_never_satisfied(self):
        for declared in (5, ["python"], "", "   "):
            with self.subTest(declared=declared):
                plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": declared}]),
                             active_topic={"topic": "python"})
                self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)


# ----------------------------------------------------------------------
class TestReferenceRelevance(unittest.TestCase):
    """9. Resolved references, when available."""

    RESOLVED = {"has_reference": True, "reference_text": "that one",
                "resolved_context": {"topic": "python"}, "ambiguous": False}

    def test_a_reference_pattern_applies_when_a_reference_is_resolved(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "reference": True}]),
                     references=[dict(self.RESOLVED)])
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["selected_pattern"]["matched_on"], ["reference"])

    def test_a_reference_pattern_can_name_the_resolved_reference(self):
        patterns = [{"id": "that", "reference": "That One"}, {"id": "this", "reference": "this"}]
        plan = _plan(meaning=_meaning(patterns=patterns), references=[dict(self.RESOLVED)])
        self.assertEqual(_select(plan).to_dict()["selected_pattern"]["pattern_id"], "that")

    def test_an_unresolved_reference_is_not_evidence(self):
        unresolved = dict(self.RESOLVED, resolved_context=None)
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "reference": True}]),
                     references=[unresolved])
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_an_ambiguous_reference_is_not_evidence(self):
        ambiguous = dict(self.RESOLVED, ambiguous=True)
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "reference": True}]),
                     references=[ambiguous])
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_reference_pattern_needs_a_reference(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "reference": True}]))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_a_reference_free_pattern_ignores_references(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p"}]), references=[dict(self.RESOLVED)])
        self.assertEqual(_select(plan).status, STATUS_RESOLVED)

    def test_a_reference_and_topic_pattern_beats_either_alone(self):
        patterns = [{"id": "ref_only", "reference": True}, {"id": "topic_only", "topic": "python"},
                    {"id": "both", "reference": True, "topic": "python"}]
        plan = _plan(meaning=_meaning(patterns=patterns), references=[dict(self.RESOLVED)],
                     active_topic={"topic": "python"})
        result = _select(plan).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "both")
        self.assertEqual(result["selected_pattern"]["matched_on"], ["topic", "reference"])

    def test_a_malformed_reference_is_never_satisfied(self):
        for declared in (False, 1, ["that one"], ""):
            with self.subTest(declared=declared):
                plan = _plan(meaning=_meaning(patterns=[{"id": "p", "reference": declared}]),
                             references=[dict(self.RESOLVED)])
                self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)


# ----------------------------------------------------------------------
class TestAmbiguityIsPreserved(unittest.TestCase):
    """10. An ambiguity the existing pipeline left open is preserved,
    never resolved by picking a response pattern."""

    def _ambiguous(self):
        return _plan(meaning_candidates=[
            _meaning("gratitude", [{"id": "thank_back"}]),
            _meaning("farewell", [{"id": "wave_back"}], meaning_id=2),
        ])

    def test_undecided_meanings_keep_every_candidate_and_select_none(self):
        result = _select(self._ambiguous()).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(result["reason"], REASON_UNDECIDED_UNDERSTANDING)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(_ids(result), ["thank_back", "wave_back"])
        for candidate in result["candidates"]:
            self.assertEqual(candidate["origin"]["kind"], ORIGIN_UNDECIDED_MEANING)

    def test_one_undecided_meaning_with_a_pattern_is_still_never_selected(self):
        plan = _plan(meaning_candidates=[
            _meaning("gratitude", [{"id": "only_one"}]), _meaning("farewell", None, meaning_id=2)])
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(_ids(result), ["only_one"])

    def test_undecided_meanings_without_patterns_are_not_found(self):
        plan = _plan(meaning_candidates=[_meaning("a"), _meaning("b", meaning_id=2)])
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_an_ambiguous_plan_never_selects_even_a_uniquely_eligible_pattern(self):
        plan = _plan(meaning_candidates=[_meaning("a"), _meaning("b", meaning_id=2)],
                     matched_pattern=_pattern([{"id": "on_pattern"}]))
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(_ids(result), ["on_pattern"])

    def test_an_ambiguous_plan_without_meaning_candidates_still_never_selects(self):
        # e.g. several learned sentence patterns matched equally (the plan
        # carries no matched_pattern) while a resolved expression has one
        plan = _plan(expression_meanings=[_expression("python", [{"id": "e"}])],
                     status=PLAN_AMBIGUOUS)
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(result["selected_pattern"])

    def test_undecided_candidates_are_still_filtered_by_their_conditions(self):
        plan = _plan(meaning_candidates=[
            _meaning("a", [{"id": "kept"}]), _meaning("b", [{"id": "dropped", "locale": "en-GB"}],
                                                      meaning_id=2)])
        self.assertEqual(_ids(_select(plan).to_dict()), ["kept"])

    def test_undecided_expression_meanings_contribute_no_candidates(self):
        undecided = _expression("bank", [{"id": "hidden"}], status="AMBIGUOUS")
        plan = _plan(meaning=_meaning(patterns=[{"id": "visible"}]),
                     expression_meanings=[undecided])
        result = _select(plan).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["selected_pattern"]["pattern_id"], "visible")

    def test_ambiguity_is_preserved_in_the_generation_context(self):
        context = build_generation_context(self._ambiguous())
        selection = context.response_pattern_selection
        self.assertEqual(selection["status"], STATUS_AMBIGUOUS)
        self.assertEqual(_ids(selection), ["thank_back", "wave_back"])
        self.assertEqual(context.status, PLAN_AMBIGUOUS)


# ----------------------------------------------------------------------
class TestNoInventedPattern(unittest.TestCase):
    """11. A pattern is only ever one that was taught - never invented,
    repaired, completed or generated."""

    def test_an_entry_without_an_id_is_ignored_not_repaired(self):
        plan = _plan(meaning=_meaning(patterns=[{"template": "no id"}, {"id": ""}, {"id": "  "},
                                                {"id": 5}, {"id": None}]))
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)

    def test_pattern_id_and_name_are_accepted_as_the_id(self):
        for key in ("id", "pattern_id", "name"):
            with self.subTest(key=key):
                plan = _plan(meaning=_meaning(patterns=[{key: "taught"}]))
                self.assertEqual(_select(plan).to_dict()["selected_pattern"]["pattern_id"], "taught")

    def test_non_dict_entries_are_ignored(self):
        plan = _plan(meaning=_meaning(patterns=["text", 3, None, ["x"], {"id": "real"}]))
        self.assertEqual(_select(plan).to_dict()["selected_pattern"]["pattern_id"], "real")

    def test_every_returned_pattern_was_taught(self):
        taught = [{"id": "a"}, {"id": "b", "topic": "python"}, {"id": "c", "locale": "xx"}]
        plan = _plan(meaning=_meaning(patterns=taught), active_topic={"topic": "python"})
        result = _select(plan).to_dict()
        for candidate in [result["selected_pattern"]] + result["candidates"]:
            if candidate is not None:
                self.assertIn(candidate["pattern"], taught)

    def test_no_text_is_generated_and_no_field_is_added_to_a_pattern(self):
        taught = {"id": "bare"}
        result = _select(_plan(meaning=_meaning(patterns=[taught]))).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern"], {"id": "bare"})
        self.assertNotIn("response_text", result)
        self.assertNotIn("response_text", result["selected_pattern"])

    def test_meanings_that_taught_nothing_yield_nothing_even_with_actions(self):
        meaning = _meaning()
        meaning["meaning"] = {"response_action": "greet"}
        result = _select(_plan(meaning=meaning)).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)

    def test_an_unresolved_plan_with_nothing_learned_invents_nothing(self):
        result = _select(_plan(status=PLAN_UNRESOLVED)).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(result["candidates"], [])

    def test_a_declared_condition_is_never_relaxed_to_find_a_pattern(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "p", "topic": "python", "locale": "en-GB"}]),
                     active_topic={"topic": "python"}, locale="en-US")
        self.assertEqual(_select(plan).status, STATUS_NOT_FOUND)


# ----------------------------------------------------------------------
class TestDeterministicSelection(unittest.TestCase):
    """12. The same input always gives the same selection."""

    def _plan(self):
        patterns = [{"id": "a", "language": "en"}, {"id": "b", "language": "en"},
                    {"id": "c", "topic": "x"}]
        return _plan(meaning=_meaning(patterns=patterns), matched_pattern=_pattern(
            [{"id": "d", "language": "en"}]), active_topic={"topic": "x"})

    def test_repeated_selection_is_identical(self):
        plan = self._plan()
        first = _select(plan).to_dict()
        for _ in range(25):
            self.assertEqual(_select(plan).to_dict(), first)

    def test_a_fresh_selector_gives_the_same_result(self):
        plan = self._plan()
        self.assertEqual(LearnedResponsePatternSelector().select(plan).to_dict(),
                         LearnedResponsePatternSelector().select(copy.deepcopy(plan)).to_dict())

    def test_the_module_function_matches_the_selector(self):
        plan = self._plan()
        self.assertEqual(select_learned_response_pattern(plan).to_dict(),
                         _select(plan).to_dict())

    def test_candidate_order_does_not_depend_on_dict_key_order(self):
        plan_a = _plan(meaning=_meaning(patterns=[{"id": "a", "language": "en", "topic": "t"},
                                                  {"id": "b", "language": "en", "topic": "t"}]),
                       active_topic={"topic": "t"})
        plan_b = _plan(meaning=_meaning(patterns=[{"topic": "t", "language": "en", "id": "a"},
                                                  {"topic": "t", "id": "b", "language": "en"}]),
                       active_topic={"topic": "t"})
        self.assertEqual(_ids(_select(plan_a).to_dict()), _ids(_select(plan_b).to_dict()))

    def test_the_result_does_not_depend_on_confidence(self):
        low = {"id": "a", "confidence": 0.1}
        high = {"id": "b", "confidence": 0.99}
        result = _select(_plan(meaning=_meaning(patterns=[low, high]))).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(_ids(result), ["a", "b"])

    def test_selection_does_not_mutate_its_input(self):
        plan = self._plan()
        before = copy.deepcopy(plan)
        _select(plan)
        self.assertEqual(plan, before)


# ----------------------------------------------------------------------
class TestBoundedSelection(unittest.TestCase):
    """13. Selection is bounded and never scans beyond the context."""

    def test_a_single_source_is_capped(self):
        patterns = [{"id": f"p{i}"} for i in range(MAX_PATTERNS_PER_SOURCE + 30)]
        result = _select(_plan(meaning=_meaning(patterns=patterns))).to_dict()
        self.assertTrue(result["truncated"])
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(len(result["candidates"]), MAX_PATTERNS_PER_SOURCE)
        self.assertEqual(_ids(result), [f"p{i}" for i in range(MAX_PATTERNS_PER_SOURCE)])

    def test_the_total_number_of_candidates_is_capped(self):
        expressions = [
            _expression(f"word{i}", [{"id": f"e{i}_{j}"} for j in range(MAX_PATTERNS_PER_SOURCE)])
            for i in range(10)]
        plan = _plan(meaning=_meaning(patterns=[{"id": f"m{i}"} for i in range(20)]),
                     matched_pattern=_pattern([{"id": f"s{i}"} for i in range(20)]),
                     expression_meanings=expressions)
        result = _select(plan).to_dict()
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["candidates"]), MAX_CANDIDATES)

    def test_truncation_is_deterministic_and_keeps_taught_order(self):
        patterns = [{"id": f"p{i}"} for i in range(MAX_PATTERNS_PER_SOURCE * 3)]
        plan = _plan(meaning=_meaning(patterns=patterns))
        self.assertEqual(_select(plan).to_dict(), _select(plan).to_dict())

    def test_a_pattern_beyond_the_bound_is_never_examined(self):
        patterns = [{"id": f"p{i}"} for i in range(MAX_PATTERNS_PER_SOURCE)]
        patterns.append({"id": "beyond_the_bound", "topic": "python"})
        plan = _plan(meaning=_meaning(patterns=patterns), active_topic={"topic": "python"})
        result = _select(plan).to_dict()
        self.assertTrue(result["truncated"])
        self.assertNotIn("beyond_the_bound", [c["pattern_id"] for c in result["candidates"]])
        self.assertIsNone(result["selected_pattern"])

    def test_within_the_bound_nothing_is_truncated(self):
        patterns = [{"id": f"p{i}"} for i in range(MAX_PATTERNS_PER_SOURCE)]
        self.assertFalse(_select(_plan(meaning=_meaning(patterns=patterns))).truncated)

    def test_ineligible_entries_count_toward_the_bound_too(self):
        patterns = [{"id": f"x{i}", "locale": "xx"} for i in range(MAX_PATTERNS_PER_SOURCE)]
        patterns.append({"id": "late"})
        result = _select(_plan(meaning=_meaning(patterns=patterns))).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertTrue(result["truncated"])


# ----------------------------------------------------------------------
class TestSelectorInputs(unittest.TestCase):
    """The selector's own contract: what it accepts and reads."""

    def test_it_accepts_a_response_plan_object(self):
        understanding_free_plan = ResponsePlan(
            original_message="hi", detected_language="english", locale=None,
            status=PLAN_RESOLVED, reason=None, needs_clarification=False,
            response_action=None, response_action_source=None,
            meaning=_meaning(patterns=[{"id": "g"}]), meaning_candidates=[], matched_pattern=None,
            pattern_candidates=[], variables={}, expression_meanings=[], active_topic=None,
            references=[], context=None, required_items=[], unresolved_requirements=[],
            understanding_state={}, warnings=[])
        result = _select(understanding_free_plan).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "g")

    def test_it_accepts_a_generation_context_and_its_dict(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "g"}]))
        context = build_generation_context(plan)
        self.assertEqual(_select(context).to_dict(), _select(plan).to_dict())
        self.assertEqual(_select(context.to_dict()).to_dict(), _select(plan).to_dict())

    def test_an_explicit_guidance_object_or_dict_is_honored(self):
        plan = _plan(meaning=_meaning(patterns=[{"id": "from_plan"}]))
        other = _plan(meaning=_meaning(patterns=[{"id": "from_guidance"}]))
        guidance = build_language_guidance(other)
        self.assertIsInstance(guidance, LearnedLanguageGuidance)
        self.assertEqual(_select(plan, guidance).to_dict()["selected_pattern"]["pattern_id"],
                         "from_guidance")
        self.assertEqual(_select(plan, guidance.to_dict()).to_dict()["selected_pattern"]
                         ["pattern_id"], "from_guidance")

    def test_a_context_with_no_guidance_selects_from_its_sentence_pattern_only(self):
        context = build_generation_context(
            _plan(meaning=_meaning(patterns=[{"id": "m"}]),
                  matched_pattern=_pattern([{"id": "s"}]))).to_dict()
        context["language_guidance"] = None
        result = _select(context).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern_id"], "s")

    def test_a_value_of_the_wrong_type_raises_type_error(self):
        for bad in (None, "plan", 5, ["x"], object()):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    _select(bad)

    def test_persian_text_is_preserved_exactly(self):
        taught = {"id": "پاسخ", "template": "چرا {{X}} را دوست داری؟", "language": "fa",
                  "topic": "غذا\u200cها"}
        plan = _plan(meaning=_meaning(patterns=[taught]), language="persian",
                     active_topic={"topic": "غذا\u200cها"})
        result = _select(plan).to_dict()
        self.assertEqual(result["selected_pattern"]["pattern"], taught)
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=False)), result)

    def test_to_dict_is_a_fresh_copy_each_time(self):
        selection = _select(_plan(meaning=_meaning(patterns=[{"id": "g", "nested": {"a": 1}}])))
        first = selection.to_dict()
        first["selected_pattern"]["pattern"]["nested"]["a"] = 99
        first["status"] = "TAMPERED"
        again = selection.to_dict()
        self.assertEqual(again["status"], STATUS_RESOLVED)
        self.assertEqual(again["selected_pattern"]["pattern"]["nested"], {"a": 1})

    def test_mutating_the_input_afterwards_does_not_change_a_made_selection(self):
        taught = {"id": "g", "nested": {"a": 1}}
        plan = _plan(meaning=_meaning(patterns=[taught]))
        selection = _select(plan)
        taught["nested"]["a"] = 99
        plan["meaning"]["meaning"]["response_patterns"][0]["id"] = "changed"
        self.assertEqual(selection.to_dict()["selected_pattern"]["pattern"]["nested"], {"a": 1})
        self.assertEqual(selection.to_dict()["selected_pattern"]["pattern_id"], "g")


# ----------------------------------------------------------------------
class TestRealPipelineSelection(_PipelineCase):
    """Real Understanding Engine + real stores; response patterns taught
    through the existing operations."""

    def test_a_pattern_taught_on_a_bound_meaning_is_selected(self):
        self.teach_meaning("greeting", [{"id": "greet_back", "template": "Good morning!"}])
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        selection = response_pattern_selection_from_understanding(understanding).to_dict()
        self.assertEqual(selection["status"], STATUS_RESOLVED)
        self.assertEqual(selection["selected_pattern"]["pattern_id"], "greet_back")
        self.assertEqual(selection["selected_pattern"]["origin"]["kind"], ORIGIN_MEANING)
        self.assertEqual(selection["language"], "english")

    def test_a_pattern_taught_on_a_sentence_pattern_is_selected(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"]}]})
        understanding = self.understand("what is python")
        selection = response_pattern_selection_from_understanding(understanding).to_dict()
        self.assertEqual(selection["status"], STATUS_RESOLVED)
        self.assertEqual(selection["selected_pattern"]["pattern_id"], "answer_question")
        self.assertEqual(selection["selected_pattern"]["origin"]["kind"], ORIGIN_SENTENCE_PATTERN)
        self.assertEqual(selection["selected_pattern"]["matched_on"], ["variables"])

    def test_a_pattern_taught_on_a_learned_expression_is_selected(self):
        self.items.learn_item("en", "word", "python", meaning={
            "gloss": "a language", RESPONSE_PATTERNS_KEY: [{"id": "about_python"}]})
        understanding = self.understand("I like python")
        selection = response_pattern_selection_from_understanding(understanding).to_dict()
        self.assertEqual(selection["status"], STATUS_RESOLVED)
        self.assertEqual(selection["selected_pattern"]["origin"]["kind"], ORIGIN_EXPRESSION)

    def test_persian_pattern_with_language_locale_and_variables(self):
        self.teach(PREFERENCE_PATTERN, language="fa", locale="fa-IR", meaning={
            RESPONSE_PATTERNS_KEY: [
                {"id": "ask_why", "language": "fa", "locale": "fa-IR", "variables": ["X"],
                 "template": "چرا {{X}} را دوست داری؟"},
                {"id": "wrong_locale", "locale": "fa-AF"},
                {"id": "wrong_language", "language": "en"},
            ]})
        self.bind(PREFERENCE_PATTERN, "express_preference", language="fa")
        understanding = self.understand("من چای را دوست دارم", requested_language="fa")
        selection = response_pattern_selection_from_understanding(understanding).to_dict()
        self.assertEqual(selection["status"], STATUS_RESOLVED)
        self.assertEqual(selection["selected_pattern"]["pattern_id"], "ask_why")
        self.assertEqual(selection["selected_pattern"]["pattern"]["template"],
                         "چرا {{X}} را دوست داری؟")
        self.assertEqual(selection["selected_pattern"]["matched_on"],
                         ["language", "locale", "variables"])
        self.assertEqual((selection["language"], selection["locale"]), ("persian", "fa-IR"))

    def test_two_bound_meanings_with_patterns_stay_ambiguous(self):
        self.teach("thanks {{who}}")
        self.teach_meaning("gratitude", [{"id": "you_are_welcome"}])
        self.teach_meaning("farewell", [{"id": "goodbye_back"}])
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        understanding = self.understand("thanks bob")
        self.assertEqual(understanding.response_plan["status"], PLAN_AMBIGUOUS)
        selection = response_pattern_selection_from_understanding(understanding).to_dict()
        self.assertEqual(selection["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(selection["selected_pattern"])
        self.assertEqual(sorted(_ids(selection)), ["goodbye_back", "you_are_welcome"])

    def test_two_equally_valid_patterns_on_one_meaning_are_ambiguous(self):
        self.teach_meaning("greeting", [{"id": "one"}, {"id": "two"}])
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        selection = response_pattern_selection_from_understanding(
            self.understand("good morning")).to_dict()
        self.assertEqual(selection["status"], STATUS_AMBIGUOUS)
        self.assertEqual(_ids(selection), ["one", "two"])

    def test_nothing_taught_is_not_found(self):
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        selection = response_pattern_selection_from_understanding(
            self.understand("good morning")).to_dict()
        self.assertEqual(selection["status"], STATUS_NOT_FOUND)

    def test_a_message_matching_nothing_is_not_found(self):
        self.teach_meaning("greeting", [{"id": "greet_back"}])
        selection = response_pattern_selection_from_understanding(
            self.understand("qwerty zzznoxyzzz unmapped concept")).to_dict()
        self.assertEqual(selection["status"], STATUS_NOT_FOUND)

    def test_patterns_of_unrelated_learned_items_are_never_included(self):
        self.teach_meaning("greeting", [{"id": "greet_back"}])
        self.teach_meaning("farewell", [{"id": "unrelated_farewell"}])
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        self.items.learn_item("en", "word", "rust", meaning={
            RESPONSE_PATTERNS_KEY: [{"id": "unrelated_word"}]})
        selection = response_pattern_selection_from_understanding(
            self.understand("good morning")).to_dict()
        self.assertEqual(selection["selected_pattern"]["pattern_id"], "greet_back")
        self.assertNotIn("unrelated", json.dumps(selection))

    def test_selection_reads_no_store_at_all(self):
        # bounded: a pure function of the plan/guidance already in hand - no
        # language-learning table, memory or knowledge query is made
        self.teach_meaning("greeting", [{"id": "greet_back"}])
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        for index in range(30):
            self.items.learn_item("en", "meaning", f"other_{index}", meaning={
                RESPONSE_PATTERNS_KEY: [{"id": f"unrelated_{index}"}]})
        understanding = self.understand("good morning")
        with mock.patch.object(self.memory, "query", wraps=self.memory.query) as query, \
                mock.patch.object(self.memory, "query_one", wraps=self.memory.query_one) as one, \
                mock.patch.object(self.memory, "_run", wraps=self.memory._run) as run:
            selection = response_pattern_selection_from_understanding(understanding).to_dict()
            generation_context_from_understanding(understanding)
            generation_request_from_understanding(understanding)
        self.assertEqual((query.call_count, one.call_count, run.call_count), (0, 0, 0))
        self.assertEqual(selection["selected_pattern"]["pattern_id"], "greet_back")
        self.assertNotIn("unrelated", json.dumps(selection))

    def test_selection_writes_nothing_to_the_language_learning_store(self):
        self.teach_meaning("greeting", [{"id": "greet_back"}])
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        before = self.memory.query("SELECT * FROM language_learning_items ORDER BY id")
        events_before = len(self.memory.query("SELECT * FROM learning_events"))
        for _ in range(3):
            response_pattern_selection_from_understanding(understanding)
            generation_context_from_understanding(understanding)
        self.assertEqual(self.memory.query("SELECT * FROM language_learning_items ORDER BY id"),
                         before)
        self.assertEqual(len(self.memory.query("SELECT * FROM learning_events")), events_before)

    def test_no_understanding_plan_means_no_selection(self):
        self.assertIsNone(response_pattern_selection_from_understanding(object()))

    def test_repeated_real_selection_is_identical(self):
        self.teach_meaning("greeting", [{"id": "a", "language": "en"}, {"id": "b"}])
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        first = response_pattern_selection_from_understanding(understanding).to_dict()
        for _ in range(10):
            self.assertEqual(
                response_pattern_selection_from_understanding(understanding).to_dict(), first)
        self.assertEqual(first["selected_pattern"]["pattern_id"], "a")


# ----------------------------------------------------------------------
class TestCompatibleWithResponseGenerationContext(_PipelineCase):
    """14. The selection rides on the existing ResponseGenerationContext,
    after guidance, without changing anything already there."""

    def _taught_greeting(self):
        self.teach_meaning("greeting", [{"id": "greet_back", "template": "Good morning!"}],
                           response_action="greet")
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        return self.understand("good morning")

    def test_the_context_carries_the_selection(self):
        understanding = self._taught_greeting()
        context = generation_context_from_understanding(understanding)
        self.assertIsInstance(context, ResponseGenerationContext)
        self.assertEqual(context.response_pattern_selection["status"], STATUS_RESOLVED)
        self.assertEqual(context.response_pattern_selection["selected_pattern"]["pattern_id"],
                         "greet_back")
        self.assertEqual(context.to_dict()["response_pattern_selection"],
                         context.response_pattern_selection)

    def test_the_contexts_selection_equals_the_selectors_own(self):
        understanding = self._taught_greeting()
        context = generation_context_from_understanding(understanding)
        self.assertEqual(context.response_pattern_selection,
                         response_pattern_selection_from_understanding(understanding).to_dict())
        plan = understanding.response_plan
        self.assertEqual(
            context.response_pattern_selection,
            select_learned_response_pattern(
                plan, language_guidance_from_understanding(understanding)).to_dict())

    def test_every_existing_context_field_is_unchanged(self):
        understanding = self._taught_greeting()
        plan = understanding.response_plan
        data = generation_context_from_understanding(understanding).to_dict()
        self.assertEqual(data["status"], plan["status"])
        self.assertEqual(data["response_action"], "greet")
        self.assertEqual(data["meaning"], plan["meaning"])
        self.assertEqual(data["matched_pattern"], plan["matched_pattern"])
        self.assertEqual(data["variables"], plan["variables"])
        self.assertEqual(data["language"], plan["detected_language"])
        self.assertEqual(data["locale"], plan["locale"])
        self.assertEqual(data["language_guidance"],
                         language_guidance_from_understanding(understanding).to_dict())
        for key in ("original_message", "meaning_candidates", "active_topic", "references",
                    "context", "unresolved_requirements"):
            self.assertIn(key, data)

    def test_a_context_with_no_learned_response_pattern_carries_not_found(self):
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        context = generation_context_from_understanding(self.understand("good morning"))
        self.assertEqual(context.response_pattern_selection["status"], STATUS_NOT_FOUND)
        self.assertIsNone(context.response_pattern_selection["selected_pattern"])
        self.assertTrue(context.resolved)  # the rest of the context is untouched

    def test_context_status_and_action_do_not_depend_on_the_selection(self):
        with_patterns = self._taught_greeting()
        plan = with_patterns.response_plan
        without = copy.deepcopy(plan)
        without["meaning"]["meaning"].pop(RESPONSE_PATTERNS_KEY)
        a = build_generation_context(plan).to_dict()
        b = build_generation_context(without).to_dict()
        for key in ("status", "response_action", "meaning_candidates", "matched_pattern",
                    "variables", "language", "locale", "unresolved_requirements"):
            self.assertEqual(a[key], b[key], key)

    def test_the_selection_follows_the_guidance_built_from_the_same_plan(self):
        understanding = self._taught_greeting()
        plan = understanding.response_plan
        context = build_generation_context(
            plan, sentence_structure=understanding.learned_sentence_structure)
        guidance = build_language_guidance(
            plan, sentence_structure=understanding.learned_sentence_structure)
        self.assertEqual(context.language_guidance, guidance.to_dict())
        self.assertEqual(context.response_pattern_selection,
                         select_learned_response_pattern(plan, guidance).to_dict())

    def test_the_contexts_selection_is_independent_of_the_plan_and_understanding(self):
        understanding = self._taught_greeting()
        context = generation_context_from_understanding(understanding)
        snapshot = copy.deepcopy(context.to_dict())
        context.response_pattern_selection["selected_pattern"]["pattern"]["template"] = "X"
        context.to_dict()["response_pattern_selection"]["status"] = "TAMPERED"
        self.assertEqual(
            understanding.response_plan["meaning"]["meaning"][RESPONSE_PATTERNS_KEY][0]["template"],
            "Good morning!")
        fresh = generation_context_from_understanding(understanding).to_dict()
        self.assertEqual(fresh["response_pattern_selection"], snapshot["response_pattern_selection"])

    def test_a_context_built_by_hand_without_a_selection_still_works(self):
        context = ResponseGenerationContext(
            original_message="hi", status=PLAN_RESOLVED, response_action=None, meaning=None,
            meaning_candidates=[], matched_pattern=None, variables={}, active_topic=None,
            references=[], context=None, language="english", locale=None,
            unresolved_requirements=[])
        self.assertIsNone(context.response_pattern_selection)
        self.assertIsNone(context.to_dict()["response_pattern_selection"])
        self.assertIsNone(context.to_dict()["language_guidance"])

    def test_the_bad_plan_type_contract_of_the_context_builder_is_unchanged(self):
        with self.assertRaises(TypeError):
            build_generation_context("not a plan")

    def test_the_context_is_json_shaped(self):
        json.dumps(generation_context_from_understanding(self._taught_greeting()).to_dict(),
                   ensure_ascii=False)


# ----------------------------------------------------------------------
class TestCompatibleWithResponseGenerationRequest(_PipelineCase):
    """15. The selection reaches `ResponseGenerationRequest` and
    `BackendGenerationRequest` unchanged; nothing downstream changes."""

    def _taught(self):
        self.teach_meaning("greeting", [{"id": "greet_back"}])
        self.teach(GREETING_PATTERN)
        self.bind(GREETING_PATTERN, "greeting")
        return self.understand("good morning")

    def test_the_backend_generation_request_carries_the_selection_unchanged(self):
        understanding = self._taught()
        request = generation_request_from_understanding(understanding)
        self.assertIsInstance(request, BackendGenerationRequest)
        context = generation_context_from_understanding(understanding)
        self.assertEqual(request.response_pattern_selection, context.response_pattern_selection)
        self.assertEqual(request.to_dict()["response_pattern_selection"]["selected_pattern"]
                         ["pattern_id"], "greet_back")

    def test_build_generation_request_carries_it_from_a_context_or_its_dict(self):
        context = generation_context_from_understanding(self._taught())
        for source in (context, context.to_dict()):
            request = build_generation_request(source)
            self.assertEqual(request.response_pattern_selection,
                             context.response_pattern_selection)

    def test_the_request_accessors_expose_the_selection(self):
        understanding = self._taught()
        request = ResponseGenerationRequest(understanding)
        self.assertEqual(request.generation_context["response_pattern_selection"]["status"],
                         STATUS_RESOLVED)
        self.assertEqual(request.generation_request["response_pattern_selection"]["status"],
                         STATUS_RESOLVED)
        self.assertEqual(request.generation_context["response_pattern_selection"],
                         request.generation_request["response_pattern_selection"])

    def test_every_existing_request_field_is_unchanged(self):
        understanding = self._taught()
        data = generation_request_from_understanding(understanding).to_dict()
        plan = understanding.response_plan
        self.assertEqual(data["status"], plan["status"])
        self.assertEqual(data["meaning"], plan["meaning"])
        self.assertEqual(data["matched_pattern"], plan["matched_pattern"])
        self.assertEqual(data["sentence_structure"], understanding.learned_sentence_structure)
        self.assertEqual(data["language_guidance"],
                         language_guidance_from_understanding(understanding).to_dict())
        for key in ("original_message", "response_action", "meaning_candidates", "variables",
                    "active_topic", "references", "context", "language", "locale",
                    "unresolved_requirements"):
            self.assertIn(key, data)

    def test_a_request_built_by_hand_without_a_selection_still_works(self):
        request = BackendGenerationRequest(
            original_message="hi", status=PLAN_RESOLVED, response_action=None, meaning=None,
            meaning_candidates=[], matched_pattern=None, sentence_structure=None, variables={},
            active_topic=None, references=[], context=None, language="english", locale=None,
            unresolved_requirements=[])
        self.assertIsNone(request.response_pattern_selection)
        self.assertIsNone(request.to_dict()["response_pattern_selection"])

    def test_the_request_selection_is_an_independent_copy(self):
        understanding = self._taught()
        request = generation_request_from_understanding(understanding)
        request.response_pattern_selection["status"] = "TAMPERED"
        request.to_dict()["response_pattern_selection"]["candidates"].append("x")
        again = generation_request_from_understanding(understanding)
        self.assertEqual(again.response_pattern_selection["status"], STATUS_RESOLVED)
        self.assertEqual(again.response_pattern_selection["candidates"], [])

    def test_no_plan_means_no_request_and_no_selection(self):
        class _NoPlan:
            response_plan = None
            learned_sentence_structure = None
        self.assertIsNone(generation_request_from_understanding(_NoPlan()))
        self.assertIsNone(generation_context_from_understanding(_NoPlan()))
        self.assertIsNone(ResponseGenerationRequest(_NoPlan()).generation_context)

    def test_the_deterministic_backend_still_defers_and_generates_no_text(self):
        understanding = self._taught()
        result = self.backend.generate_response(ResponseGenerationRequest(understanding))
        self.assertEqual(result.status, STATUS_DEFERRED)
        self.assertIsNone(result.response_text)


# ----------------------------------------------------------------------
class TestCoreIntegrationUnaffected(unittest.TestCase):
    """Regression: Core's existing understand/generate path is unaffected
    by the presence of the selection."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = Core(memory_db_path=os.path.join(self._tmp.name, "core.db"),
                         skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        self.assertEqual(
            self.core.teach_sentence_pattern("en", GREETING_PATTERN).status, STATUS_CREATED)
        bound = self.core.bind_pattern_meaning("en", GREETING_PATTERN, "greeting")
        self.assertTrue(bound.success, bound.errors)

    def _teach_response_pattern(self):
        self.core.learn_language_item("en", "meaning", "greeting", meaning={
            "response_action": "greet",
            RESPONSE_PATTERNS_KEY: [{"id": "greet_back", "template": "Good morning!"}]})

    def test_generation_context_via_core_includes_the_selection(self):
        self._teach_response_pattern()
        understanding = self.core.understand_language("good morning")
        ctx = ResponseGenerationRequest(understanding, context=self.core.context).generation_context
        self.assertEqual(ctx["response_pattern_selection"]["status"], STATUS_RESOLVED)
        self.assertEqual(ctx["response_pattern_selection"]["selected_pattern"]["pattern_id"],
                         "greet_back")
        # every prior field is still exactly as before
        self.assertEqual(ctx["response_action"], "greet")
        self.assertEqual(ctx["original_message"], "good morning")
        self.assertEqual(ctx["language_guidance"]["pattern_meaning"]["meaning"]["meaning_name"],
                         "greeting")

    def test_generation_request_via_core_includes_the_selection(self):
        self._teach_response_pattern()
        understanding = self.core.understand_language("good morning")
        req = ResponseGenerationRequest(understanding, context=self.core.context).generation_request
        self.assertEqual(req["response_pattern_selection"]["selected_pattern"]["pattern_id"],
                         "greet_back")

    def test_behavior_is_preserved_when_no_response_pattern_is_taught(self):
        understanding = self.core.understand_language("good morning")
        ctx = ResponseGenerationRequest(understanding, context=self.core.context).generation_context
        self.assertEqual(ctx["response_pattern_selection"]["status"], STATUS_NOT_FOUND)
        self.assertEqual(ctx["response_action"], "greet")
        self.assertEqual(ctx["status"], "RESOLVED")

    def test_deterministic_generation_is_still_deferred_with_no_text(self):
        # Prompt 437: a VALID learned response (the selected pattern here has
        # no variables) is now used directly, so the deterministic backend's
        # DEFERRED result is checked with no response pattern taught.
        understanding = self.core.understand_language("good morning")
        response = self.core.generate_language_response(understanding)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)

    def test_a_valid_selected_pattern_is_used_as_the_learned_response(self):
        self._teach_response_pattern()
        understanding = self.core.understand_language("good morning")
        response = self.core.generate_language_response(understanding)
        self.assertEqual(response.response_text, "Good morning!")
        self.assertEqual(response.backend_kind, "learned_response")

    def test_an_understanding_of_an_unrelated_message_selects_nothing(self):
        self._teach_response_pattern()
        understanding = self.core.understand_language("qwerty zzznoxyzzz unmapped concept")
        ctx = ResponseGenerationRequest(understanding, context=self.core.context).generation_context
        self.assertEqual(ctx["response_pattern_selection"]["status"], STATUS_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
