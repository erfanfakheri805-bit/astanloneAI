"""
Tests for Prompt 435 - Learned Response Pattern Variable Binding.

`LearnedResponsePatternBinder` (language_intelligence/
learned_response_pattern_binding.py) binds the variables the ONE learned
response pattern Prompt 434 selected needs to values the pipeline has
already extracted - RESOLVED when every required variable is bound,
UNRESOLVED (missing variables named, resolved ones kept) otherwise - and
preserves an AMBIGUOUS / NOT_FOUND selection without binding anything.
Its result is carried by `ResponseGenerationContext.
response_pattern_binding` and, from there, `BackendGenerationRequest.
response_pattern_binding`.

Unit-level tests hand-build the plan dict the binder reads (the exact
shape `ResponsePlan.to_dict()` produces) and run the REAL Prompt 434
selector to obtain the selection, so each rule is exercised on its own.
Integration-level tests drive a real Understanding Engine and real
Prompt 416-424 stores, teach response patterns through the EXISTING
teaching/binding operations (the open stored `meaning` value), and read
the binding off the real `ResponseGenerationContext` /
`ResponseGenerationRequest`.

Run directly:
    python -m unittest tests.test_learned_response_pattern_binding -v
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
    ResponsePlanner, ResponsePlan, STATUS_RESOLVED as PLAN_RESOLVED, STATUS_AMBIGUOUS as PLAN_AMBIGUOUS,
    STATUS_UNRESOLVED as PLAN_UNRESOLVED,
)
from language_intelligence.language_guidance import (
    build_language_guidance, language_guidance_from_understanding,
)
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.response_generation import ResponseGenerationRequest, STATUS_DEFERRED
from language_intelligence.learned_response_pattern_selection import (
    select_learned_response_pattern, response_pattern_selection_from_understanding,
    RESPONSE_PATTERNS_KEY, STATUS_RESOLVED as SEL_RESOLVED, STATUS_AMBIGUOUS as SEL_AMBIGUOUS,
    STATUS_NOT_FOUND as SEL_NOT_FOUND,
)
from language_intelligence.learned_response_pattern_binding import (
    LearnedResponsePatternBinder, LearnedResponsePatternBinding,
    bind_learned_response_pattern, response_pattern_binding_from_understanding,
    STATUS_RESOLVED, STATUS_UNRESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND, ALL_STATUSES,
    REASON_ALL_BOUND, REASON_NO_VARIABLES_REQUIRED, REASON_VARIABLES_MISSING,
    REASON_NO_SELECTION, REASON_PATTERN_UNAVAILABLE, ROUTABLE_SOURCES, MAX_REQUIRED_VARIABLES,
)

from core.core import Core

QUESTION_PATTERN = "what is {{topic}}"
GREETING_PATTERN = "good morning"
PREFERENCE_PATTERN = "من {{X}} را دوست دارم"


# ----------------------------------------------------------------------
# Hand-built plan dicts (the shape `ResponsePlan.to_dict()` produces)
# ----------------------------------------------------------------------
def _meaning(name="greeting", patterns=None, **extra):
    stored = {} if patterns is None else {RESPONSE_PATTERNS_KEY: patterns}
    meaning = {
        "id": 1, "meaning_id": 1, "key": name, "meaning_name": name, "item_type": "meaning",
        "language": "english", "locale": None, "meaning": stored, "confidence": 0.9,
        "source": "unit-test", "related": [],
    }
    meaning.update(extra)
    return meaning


def _plan(meaning=None, meaning_candidates=None, matched_pattern=None, language="english",
          locale=None, active_topic=None, references=None, context=None,
          expression_meanings=None, variables=None, original_message="hello", status=None):
    if status is None:
        if meaning is not None:
            status = PLAN_RESOLVED
        elif meaning_candidates:
            status = PLAN_AMBIGUOUS
        else:
            status = PLAN_UNRESOLVED
    return {
        "original_message": original_message, "detected_language": language, "locale": locale,
        "status": status, "meaning": meaning, "meaning_candidates": meaning_candidates or [],
        "matched_pattern": matched_pattern, "variables": variables or {},
        "expression_meanings": expression_meanings or [], "active_topic": active_topic,
        "references": references or [], "context": context, "response_action": None,
        "unresolved_requirements": [],
    }


def _plan_with(patterns, **kwargs):
    """A RESOLVED plan whose bound meaning taught `patterns`."""
    return _plan(meaning=_meaning(patterns=patterns), **kwargs)


def _structure(**values):
    """A MATCHED recognized structure (guidance shape) with these variables."""
    return {"status": "MATCHED", "components": [
        {"kind": "variable", "variable_name": name, "value": value}
        for name, value in values.items()]}


def _guidance(plan, structure=None, expressions=None):
    """The REAL Prompt 433 guidance for `plan` (plus a recognized
    `structure`), with the learned-expression entries optionally replaced."""
    data = build_language_guidance(plan, sentence_structure=structure).to_dict()
    if expressions is not None:
        data["expression_meanings"] = expressions
    return data


def _resolved_expression(expression):
    return {"expression": expression, "status": "RESOLVED",
            "resolved_meaning": {"id": 5, "meaning": {}, "confidence": 0.7, "source": "x"},
            "candidates": [], "reason": None}


def _bind(plan, guidance=None):
    """The REAL Prompt 434 selection, then the binding for it."""
    selection = select_learned_response_pattern(plan, guidance)
    return LearnedResponsePatternBinder().bind(plan, selection, guidance)


def _bound(plan, guidance=None):
    return _bind(plan, guidance).to_dict()


RESOLVED_REF = {"has_reference": True, "reference_text": "that one",
                "resolved_context": "tell me about python", "ambiguous": False}


# ----------------------------------------------------------------------
class _PipelineCase(unittest.TestCase):
    """A real Understanding Engine + real Prompt 416-424 stores wired to
    a LanguageIntelligenceCore. Response patterns are taught through the
    EXISTING operations: `learn_item(..., meaning={...})` for a meaning,
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

    def bind_meaning(self, pattern, meaning, language="en", **kwargs):
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
class TestAllVariablesResolved(unittest.TestCase):
    """1-3. A unique pattern whose variables are all resolved."""

    def test_unique_pattern_with_its_variable_resolved(self):
        plan = _plan_with([{"id": "answer", "template": "About {{topic}}."}],
                          variables={"topic": "python"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["reason"], REASON_ALL_BOUND)
        self.assertEqual(result["bound_variables"], {"topic": "python"})
        self.assertEqual(result["missing_variables"], [])
        self.assertEqual(result["required_variables"], ["topic"])

    def test_the_selected_pattern_is_preserved(self):
        plan = _plan_with([{"id": "answer", "template": "About {{topic}}.", "extra": {"k": [1]}}],
                          variables={"topic": "python"})
        selection = select_learned_response_pattern(plan)
        result = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        self.assertEqual(result["selected_pattern"], selection.to_dict()["selected_pattern"])
        self.assertEqual(result["pattern_id"], "answer")
        self.assertEqual(result["selected_pattern"]["pattern"]["extra"], {"k": [1]})
        self.assertEqual(result["selected_pattern"]["origin"]["kind"], "meaning")

    def test_a_pattern_needing_one_of_several_extracted_variables_binds_only_that_one(self):
        plan = _plan_with([{"id": "p", "template": "{{b}}"}],
                          variables={"a": "1", "b": "2", "c": "3"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"], {"b": "2"})

    def test_multiple_variables_resolved(self):
        plan = _plan_with([{"id": "p", "template": "{{who}} likes {{what}} in {{where}}"}],
                          variables={"who": "Sara", "what": "tea", "where": "Tehran"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"],
                         {"who": "Sara", "what": "tea", "where": "Tehran"})
        self.assertEqual(result["required_variables"], ["who", "what", "where"])
        self.assertEqual(result["variable_sources"],
                         {"who": "extracted", "what": "extracted", "where": "extracted"})

    def test_required_variables_come_from_all_three_declarations_without_duplicates(self):
        plan = _plan_with([{"id": "p", "required_variables": ["a", "b"], "variables": ["b", "c"],
                            "template": "{{c}} {{ d }} {{a}}"}],
                          variables={"a": 1, "b": 2, "c": 3, "d": 4})
        result = _bound(plan)
        self.assertEqual(result["required_variables"], ["a", "b", "c", "d"])
        self.assertEqual(result["status"], STATUS_RESOLVED)

    def test_a_pattern_that_needs_no_variables_is_resolved_with_nothing_bound(self):
        result = _bound(_plan_with([{"id": "hello", "template": "Good morning!"}],
                                   variables={"unused": "x"}))
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["reason"], REASON_NO_VARIABLES_REQUIRED)
        self.assertEqual(result["bound_variables"], {})
        self.assertEqual(result["required_variables"], [])

    def test_variables_are_also_read_from_the_recognized_sentence_structure(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}])
        result = _bound(plan, _guidance(plan, _structure(topic="python")))
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"], {"topic": "python"})

    def test_a_structure_and_the_plan_that_agree_bind_once(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}], variables={"topic": "python"})
        result = _bound(plan, _guidance(plan, _structure(topic="python")))
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["conflicting_variables"], [])

    def test_an_unresolved_structure_contributes_no_values(self):
        structure = {"status": "NOT_RESOLVED", "components": [
            {"kind": "variable", "variable_name": "topic", "value": "python"}]}
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}])
        result = _bound(plan, _guidance(plan, structure))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["topic"])


# ----------------------------------------------------------------------
class TestMissingVariables(unittest.TestCase):
    """4-5. One or several required variables cannot be resolved."""

    def test_a_missing_variable_makes_the_binding_unresolved(self):
        result = _bound(_plan_with([{"id": "p", "template": "About {{topic}}."}]))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["reason"], REASON_VARIABLES_MISSING)
        self.assertEqual(result["missing_variables"], ["topic"])
        self.assertEqual(result["bound_variables"], {})

    def test_already_resolved_variables_are_preserved(self):
        plan = _plan_with([{"id": "p", "template": "{{who}} likes {{what}}"}],
                          variables={"who": "Sara"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["bound_variables"], {"who": "Sara"})
        self.assertEqual(result["missing_variables"], ["what"])
        self.assertEqual(result["variable_sources"], {"who": "extracted"})

    def test_multiple_missing_variables_are_all_named_in_order(self):
        plan = _plan_with([{"id": "p", "template": "{{a}} {{b}} {{c}} {{d}}"}],
                          variables={"b": "2"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["a", "c", "d"])
        self.assertEqual(result["bound_variables"], {"b": "2"})

    def test_the_selected_pattern_is_still_preserved_when_unresolved(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}"}])
        selection = select_learned_response_pattern(plan)
        result = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["selected_pattern"], selection.to_dict()["selected_pattern"])
        self.assertEqual(result["pattern_id"], "p")

    def test_a_variable_extracted_with_no_value_is_missing(self):
        for empty in (None, "", "   "):
            with self.subTest(value=repr(empty)):
                plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": empty})
                result = _bound(plan)
                self.assertEqual(result["status"], STATUS_UNRESOLVED)
                self.assertEqual(result["missing_variables"], ["a"])

    def test_a_falsy_but_real_value_is_a_value(self):
        for value in (0, False, 0.0):
            with self.subTest(value=repr(value)):
                plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": value})
                result = _bound(plan)
                self.assertEqual(result["status"], STATUS_RESOLVED)
                self.assertEqual(result["bound_variables"], {"a": value})
                self.assertIs(type(result["bound_variables"]["a"]), type(value))

    def test_variable_names_are_matched_exactly(self):
        plan = _plan_with([{"id": "p", "template": "{{Topic}}"}], variables={"topic": "python"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["Topic"])

    def test_a_declared_variable_the_pipeline_never_extracted_is_missing(self):
        # Prompt 434's `variables` condition is exercised through a rule
        # of its own; here the selection is handed in already made.
        plan = _plan_with([{"id": "p", "required_variables": ["topic"]}])
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["topic"])

    def test_malformed_variable_declarations_are_ignored_never_repaired(self):
        plan = _plan_with([{"id": "p", "required_variables": ["", 5, None, " "],
                            "template": 5}])
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["required_variables"], [])
        plan = _plan_with([{"id": "p", "required_variables": "topic", "template": ["{{topic}}"]}])
        self.assertEqual(_bound(plan)["required_variables"], [])


# ----------------------------------------------------------------------
class TestAmbiguousOrUnavailablePattern(unittest.TestCase):
    """6-7. No binding unless exactly one pattern was selected."""

    def test_equally_valid_patterns_stay_ambiguous_and_nothing_is_bound(self):
        plan = _plan_with([{"id": "one", "template": "{{a}}"}, {"id": "two", "template": "{{a}}"}],
                          variables={"a": "x"})
        selection = select_learned_response_pattern(plan)
        self.assertEqual(selection.status, SEL_AMBIGUOUS)
        result = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(result["reason"], selection.reason)
        self.assertIsNone(result["selected_pattern"])
        self.assertIsNone(result["pattern_id"])
        self.assertEqual(result["candidates"], selection.to_dict()["candidates"])
        self.assertEqual([c["pattern_id"] for c in result["candidates"]], ["one", "two"])
        self.assertEqual(result["bound_variables"], {})
        self.assertEqual(result["required_variables"], [])
        self.assertEqual(result["missing_variables"], [])

    def test_an_undecided_understanding_stays_ambiguous(self):
        plan = _plan(meaning_candidates=[_meaning("gratitude", [{"id": "thank_back"}]),
                                         _meaning("farewell", [{"id": "wave_back"}], meaning_id=2)],
                     variables={"a": "x"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(result["reason"], "understanding_not_decided")
        self.assertEqual(result["bound_variables"], {})

    def test_nothing_taught_stays_not_found(self):
        plan = _plan(meaning=_meaning(), variables={"a": "x"})
        selection = select_learned_response_pattern(plan)
        self.assertEqual(selection.status, SEL_NOT_FOUND)
        result = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["reason"], selection.reason)
        self.assertIsNone(result["selected_pattern"])
        self.assertEqual(result["bound_variables"], {})

    def test_patterns_none_of_which_apply_stay_not_found(self):
        plan = _plan_with([{"id": "p", "topic": "python", "template": "{{a}}"}],
                          variables={"a": "x"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["reason"], "no_matching_learned_response_pattern")

    def test_no_selection_at_all_is_not_found(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        for selection in (None, {}):
            with self.subTest(selection=selection):
                result = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
                self.assertEqual(result["status"], STATUS_NOT_FOUND)
                self.assertEqual(result["reason"], REASON_NO_SELECTION)
                self.assertEqual(result["bound_variables"], {})

    def test_the_binder_never_selects_a_pattern_itself(self):
        # A perfectly selectable pattern exists, but no selection was given.
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        self.assertEqual(select_learned_response_pattern(plan).status, SEL_RESOLVED)
        self.assertEqual(LearnedResponsePatternBinder().bind(plan).status, STATUS_NOT_FOUND)

    def test_a_resolved_selection_without_a_usable_pattern_is_unavailable(self):
        plan = _plan(meaning=_meaning(), variables={"a": "x"})
        for selected in (None, {"pattern_id": "p"}, {"pattern_id": "p", "pattern": "text"},
                         {"pattern_id": "p", "pattern": {"template": "{{a}}"}}):
            with self.subTest(selected=selected):
                selection = {"status": SEL_RESOLVED, "selected_pattern": selected,
                             "candidates": [], "language": "english", "locale": None}
                result = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
                self.assertEqual(result["status"], STATUS_NOT_FOUND)
                self.assertEqual(result["reason"], REASON_PATTERN_UNAVAILABLE)
                self.assertEqual(result["bound_variables"], {})

    def test_a_selection_of_an_unknown_status_is_unavailable(self):
        plan = _plan(meaning=_meaning(), variables={"a": "x"})
        result = LearnedResponsePatternBinder().bind(plan, {"status": "WHATEVER"}).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["reason"], REASON_PATTERN_UNAVAILABLE)

    def test_the_selection_carried_by_a_context_is_used_when_none_is_given(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        context = build_generation_context(plan)
        result = LearnedResponsePatternBinder().bind(context).to_dict()
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"], {"a": "x"})


# ----------------------------------------------------------------------
class TestValuesPreservedExactly(unittest.TestCase):
    """8. A bound value is the source's own, untouched."""

    def test_text_is_not_trimmed_case_folded_or_normalized(self):
        values = {"a": "  Mixed   CASE  text ", "b": "Ａ Ｂ", "c": "line1\nline2", "d": "چای  سبز"}
        plan = _plan_with([{"id": "p", "template": "{{a}}{{b}}{{c}}{{d}}"}], variables=values)
        result = _bound(plan)
        self.assertEqual(result["bound_variables"], values)

    def test_non_text_values_keep_their_type_and_structure(self):
        values = {"n": 42, "f": 3.5, "l": ["x", {"y": 1}], "d": {"k": (1, 2)}}
        plan = _plan_with([{"id": "p", "template": "{{n}}{{f}}{{l}}{{d}}"}], variables=values)
        result = _bound(plan)
        self.assertEqual(result["bound_variables"], values)
        self.assertIs(type(result["bound_variables"]["n"]), int)

    def test_the_bound_values_are_independent_copies(self):
        source_value = {"k": ["v"]}
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": source_value})
        binding = _bind(plan)
        binding.bound_variables["a"]["k"].append("tampered")
        binding.to_dict()["bound_variables"]["a"]["k"].append("tampered")
        self.assertEqual(source_value, {"k": ["v"]})
        self.assertEqual(binding.to_dict()["bound_variables"]["a"], {"k": ["v", "tampered"]})
        self.assertEqual(_bound(plan)["bound_variables"]["a"], {"k": ["v"]})

    def test_no_text_is_generated_and_the_template_is_never_rendered(self):
        plan = _plan_with([{"id": "p", "template": "Hi {{who}}!"}], variables={"who": "Sara"})
        data = _bound(plan)
        self.assertEqual(data["selected_pattern"]["pattern"]["template"], "Hi {{who}}!")
        self.assertNotIn("response_text", data)
        self.assertNotIn("Hi Sara!", repr(data))

    def test_persian_values_and_templates_are_preserved(self):
        plan = _plan_with([{"id": "ask_why", "template": "چرا {{X}} را دوست داری؟"}],
                          variables={"X": "چای"}, language="persian", locale="fa-IR")
        result = _bound(plan)
        self.assertEqual(result["bound_variables"], {"X": "چای"})
        self.assertEqual(result["selected_pattern"]["pattern"]["template"],
                         "چرا {{X}} را دوست داری؟")


# ----------------------------------------------------------------------
class TestOriginalMessageAndMetadataPreserved(unittest.TestCase):
    """9-10. The message, language, locale, source, confidence, pattern
    identity and meaning information are carried unchanged."""

    MESSAGE = "  What   IS Python?  \n"

    def _plan(self, **kwargs):
        return _plan_with([{"id": "p", "template": "{{topic}}", "confidence": 0.42,
                            "source": "taught-by-user"}],
                          variables={"topic": "python"}, original_message=self.MESSAGE, **kwargs)

    def test_the_original_message_is_preserved_exactly(self):
        for plan in (self._plan(), _plan_with([{"id": "p", "template": "{{missing}}"}],
                                              original_message=self.MESSAGE)):
            with self.subTest(status=_bound(plan)["status"]):
                self.assertEqual(_bound(plan)["original_message"], self.MESSAGE)

    def test_the_original_message_is_preserved_when_nothing_is_bound(self):
        plan = _plan(meaning=_meaning(), original_message="سلام، حال شما؟")
        self.assertEqual(_bound(plan)["original_message"], "سلام، حال شما؟")

    def test_language_and_locale_are_preserved(self):
        result = _bound(self._plan(language="persian", locale="fa-IR"))
        self.assertEqual((result["language"], result["locale"]), ("persian", "fa-IR"))

    def test_language_and_locale_are_reported_even_when_nothing_is_bound(self):
        plan = _plan(meaning=_meaning(), language="german", locale="de-DE")
        result = _bound(plan)
        self.assertEqual((result["language"], result["locale"]), ("german", "de-DE"))

    def test_confidence_and_source_are_the_selections_own(self):
        selection = select_learned_response_pattern(self._plan())
        result = LearnedResponsePatternBinder().bind(self._plan(), selection).to_dict()
        self.assertEqual((result["confidence"], result["source"]), (0.42, "taught-by-user"))
        self.assertEqual((result["confidence"], result["source"]),
                         (selection.confidence, selection.source))
        self.assertEqual(result["selected_pattern"]["confidence"], 0.42)

    def test_confidence_and_source_fall_back_to_the_carrying_item(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        result = _bound(plan)
        self.assertEqual((result["confidence"], result["source"]), (0.9, "unit-test"))

    def test_pattern_identity_and_origin_are_preserved(self):
        result = _bound(self._plan())
        self.assertEqual(result["pattern_id"], "p")
        self.assertEqual(result["selected_pattern"]["origin"],
                         {"kind": "meaning", "id": 1, "name": "greeting"})

    def test_meaning_information_is_preserved(self):
        plan = self._plan()
        result = _bound(plan)
        self.assertEqual(result["meaning"], plan["meaning"])
        self.assertEqual(result["meaning"]["meaning_name"], "greeting")

    def test_meaning_information_is_none_when_the_plan_has_none(self):
        plan = _plan(matched_pattern={
            "pattern_id": 3, "pattern_text": "x {{a}}", "language": "english", "locale": None,
            "confidence": 0.8, "source": "s",
            "meaning": {RESPONSE_PATTERNS_KEY: [{"id": "p", "template": "{{a}}"}]}},
            variables={"a": "1"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertIsNone(result["meaning"])
        self.assertEqual(result["selected_pattern"]["origin"]["kind"], "sentence_pattern")

    def test_a_result_reports_a_valid_status(self):
        for plan in (self._plan(), _plan(meaning=_meaning()),
                     _plan_with([{"id": "p", "template": "{{z}}"}])):
            self.assertIn(_bound(plan)["status"], ALL_STATUSES)


# ----------------------------------------------------------------------
class TestRoutedContextSources(unittest.TestCase):
    """3. Variables an entry routes to context the pipeline already has."""

    def _routed(self, source, **plan_kwargs):
        plan = _plan_with([{"id": "p", "template": "{{v}}", "variable_sources": {"v": source}}],
                          **plan_kwargs)
        return plan

    def test_active_topic(self):
        result = _bound(self._routed("active_topic", active_topic={"topic": "Python"}))
        self.assertEqual(result["bound_variables"], {"v": "Python"})
        self.assertEqual(result["variable_sources"], {"v": "active_topic"})

    def test_context_topic(self):
        plan = self._routed("context_topic", context={"topic": {"topic": "cooking"}})
        result = _bound(plan)
        self.assertEqual(result["bound_variables"], {"v": "cooking"})
        self.assertEqual(result["variable_sources"], {"v": "context_topic"})

    def test_the_two_topics_are_never_mixed(self):
        plan = self._routed("context_topic", active_topic={"topic": "python"})
        self.assertEqual(_bound(plan)["status"], STATUS_UNRESOLVED)
        plan = self._routed("active_topic", context={"topic": {"topic": "cooking"}})
        self.assertEqual(_bound(plan)["status"], STATUS_UNRESOLVED)

    def test_a_resolved_reference_binds_its_verbatim_text(self):
        result = _bound(self._routed("reference", references=[dict(RESOLVED_REF)]))
        self.assertEqual(result["bound_variables"], {"v": "tell me about python"})
        self.assertEqual(result["variable_sources"], {"v": "reference"})

    def test_unresolved_and_ambiguous_references_bind_nothing(self):
        for ref in (dict(RESOLVED_REF, resolved_context=None), dict(RESOLVED_REF, ambiguous=True)):
            with self.subTest(ref=ref):
                result = _bound(self._routed("reference", references=[ref]))
                self.assertEqual(result["status"], STATUS_UNRESOLVED)
                self.assertEqual(result["missing_variables"], ["v"])

    def test_several_different_resolved_references_conflict_and_none_is_picked(self):
        refs = [dict(RESOLVED_REF), dict(RESOLVED_REF, resolved_context="something else")]
        result = _bound(self._routed("reference", references=refs))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["v"])
        self.assertEqual(result["conflicting_variables"], ["v"])
        self.assertEqual(result["bound_variables"], {})

    def test_identical_resolved_references_are_one_value(self):
        refs = [dict(RESOLVED_REF), dict(RESOLVED_REF)]
        result = _bound(self._routed("reference", references=refs))
        self.assertEqual(result["status"], STATUS_RESOLVED)

    def test_a_resolved_learned_expression(self):
        plan = self._routed("expression")
        result = _bound(plan, _guidance(plan, expressions=[_resolved_expression("python")]))
        self.assertEqual(result["bound_variables"], {"v": "python"})
        self.assertEqual(result["variable_sources"], {"v": "expression"})

    def test_undecided_expressions_bind_nothing_and_several_conflict(self):
        undecided = dict(_resolved_expression("python"), status="AMBIGUOUS")
        plan = self._routed("expression")
        result = _bound(plan, _guidance(plan, expressions=[undecided]))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        two = _guidance(plan, expressions=[_resolved_expression("python"),
                                           _resolved_expression("java")])
        result = _bound(plan, two)
        self.assertEqual(result["conflicting_variables"], ["v"])
        self.assertEqual(result["bound_variables"], {})

    def test_the_resolved_meaning_name(self):
        result = _bound(self._routed("meaning"))
        self.assertEqual(result["bound_variables"], {"v": "greeting"})
        self.assertEqual(result["variable_sources"], {"v": "meaning"})

    def test_an_undecided_meaning_is_never_a_value(self):
        plan = _plan(meaning_candidates=[_meaning("a"), _meaning("b", meaning_id=2)])
        binding = LearnedResponsePatternBinder().bind(plan, {
            "status": SEL_RESOLVED, "selected_pattern": {
                "pattern_id": "p", "pattern": {"id": "p", "template": "{{v}}",
                                               "variable_sources": {"v": "meaning"}}}})
        self.assertEqual(binding.status, STATUS_UNRESOLVED)
        self.assertEqual(binding.missing_variables, ["v"])

    def test_language_and_locale_as_the_context_reports_them(self):
        plan = _plan_with([{"id": "p", "template": "{{l}} {{c}}",
                            "variable_sources": {"l": "language", "c": "locale"}}],
                          language="persian", locale="fa-IR")
        result = _bound(plan)
        self.assertEqual(result["bound_variables"], {"l": "persian", "c": "fa-IR"})

    def test_a_routed_variable_ignores_an_extracted_value_of_the_same_name(self):
        plan = self._routed("active_topic", variables={"v": "extracted"},
                            active_topic={"topic": "routed"})
        self.assertEqual(_bound(plan)["bound_variables"], {"v": "routed"})

    def test_an_unrouted_variable_never_falls_back_to_context(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}],
                          active_topic={"topic": "python"}, context={"topic": {"topic": "x"}},
                          references=[dict(RESOLVED_REF)])
        result = _bound(plan, _guidance(plan, expressions=[_resolved_expression("python")]))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["topic"])

    def test_an_unknown_or_malformed_source_binds_nothing(self):
        for route in ("weather", "", 5, ["active_topic"], "ACTIVE_TOPIC"):
            with self.subTest(route=route):
                plan = _plan_with([{"id": "p", "template": "{{v}}",
                                    "variable_sources": {"v": route}}],
                                  active_topic={"topic": "python"}, variables={})
                result = _bound(plan)
                self.assertEqual(result["status"], STATUS_UNRESOLVED)
                self.assertEqual(result["bound_variables"], {})

    def test_a_malformed_variable_sources_value_is_ignored(self):
        for holder in ("active_topic", ["v"], 5):
            with self.subTest(holder=holder):
                plan = _plan_with([{"id": "p", "template": "{{v}}", "variable_sources": holder}],
                                  active_topic={"topic": "python"})
                self.assertEqual(_bound(plan)["status"], STATUS_UNRESOLVED)

    def test_every_routable_source_is_covered_by_a_test(self):
        self.assertEqual(set(ROUTABLE_SOURCES), {
            "active_topic", "context_topic", "reference", "expression", "meaning", "language",
            "locale"})

    def test_routed_and_extracted_variables_bind_together(self):
        plan = _plan_with([{"id": "p", "template": "{{who}} / {{t}}",
                            "variable_sources": {"t": "active_topic"}}],
                          variables={"who": "Sara"}, active_topic={"topic": "python"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["variable_sources"], {"who": "extracted", "t": "active_topic"})


# ----------------------------------------------------------------------
class TestNothingIsGuessed(unittest.TestCase):
    """11. A missing variable is never given a value."""

    def test_no_default_or_placeholder_value_is_ever_bound(self):
        result = _bound(_plan_with([{"id": "p", "template": "{{a}}", "default": "x",
                                     "defaults": {"a": "y"}}]))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["bound_variables"], {})

    def test_a_value_is_never_taken_from_another_variable(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}], variables={"subject": "python"})
        result = _bound(plan)
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["topic"])

    def test_conflicting_extracted_values_are_reported_not_resolved(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}], variables={"topic": "python"})
        result = _bound(plan, _guidance(plan, _structure(topic="java")))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["topic"])
        self.assertEqual(result["conflicting_variables"], ["topic"])
        self.assertEqual(result["bound_variables"], {})

    def test_a_conflict_does_not_disturb_the_other_variables(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}} {{who}}"}],
                          variables={"topic": "python", "who": "Sara"})
        result = _bound(plan, _guidance(plan, _structure(topic="java")))
        self.assertEqual(result["bound_variables"], {"who": "Sara"})
        self.assertEqual(result["conflicting_variables"], ["topic"])

    def test_the_active_topic_is_not_a_fallback_for_a_missing_variable(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}], active_topic={"topic": "python"})
        self.assertEqual(_bound(plan)["bound_variables"], {})

    def test_the_original_message_is_never_mined_for_values(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}], original_message="what is python")
        self.assertEqual(_bound(plan)["bound_variables"], {})

    def test_variables_of_unselected_candidates_are_never_bound(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}", "topic": "python"},
                           {"id": "q", "template": "{{b}}"}],
                          variables={"a": "1", "b": "2"})
        result = _bound(plan)
        self.assertEqual(result["pattern_id"], "q")
        self.assertEqual(result["bound_variables"], {"b": "2"})

    def test_a_structure_variable_without_a_value_is_not_a_value(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}])
        result = _bound(plan, _guidance(plan, _structure(topic=None)))
        self.assertEqual(result["status"], STATUS_UNRESOLVED)


# ----------------------------------------------------------------------
class TestDeterministicAndBounded(unittest.TestCase):
    """12. Repeated binding is identical; the work is bounded."""

    def _plan(self):
        return _plan_with([{"id": "p", "template": "{{a}} {{b}} {{c}}",
                            "variable_sources": {"c": "active_topic"}}],
                          variables={"a": "1", "b": "2"}, active_topic={"topic": "t"})

    def test_repeated_binding_is_identical(self):
        plan = self._plan()
        first = _bound(plan)
        for _ in range(10):
            self.assertEqual(_bound(plan), first)

    def test_a_fresh_binder_gives_the_same_result(self):
        plan = self._plan()
        selection = select_learned_response_pattern(plan)
        one = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        two = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        self.assertEqual(one, two)

    def test_the_module_function_matches_the_binder(self):
        plan = self._plan()
        selection = select_learned_response_pattern(plan)
        self.assertEqual(bind_learned_response_pattern(plan, selection).to_dict(),
                         LearnedResponsePatternBinder().bind(plan, selection).to_dict())

    def test_binding_does_not_depend_on_variable_dict_order(self):
        forward = _plan_with([{"id": "p", "template": "{{a}}{{b}}"}], variables={"a": 1, "b": 2})
        backward = _plan_with([{"id": "p", "template": "{{a}}{{b}}"}], variables={"b": 2, "a": 1})
        self.assertEqual(_bound(forward), _bound(backward))
        self.assertEqual(list(_bound(backward)["bound_variables"]), ["a", "b"])

    def test_binding_does_not_depend_on_confidence(self):
        low = _plan_with([{"id": "p", "template": "{{a}}", "confidence": 0.01}],
                         variables={"a": "x"})
        high = _plan_with([{"id": "p", "template": "{{a}}", "confidence": 0.99}],
                          variables={"a": "x"})
        self.assertEqual(_bound(low)["bound_variables"], _bound(high)["bound_variables"])

    def test_binding_does_not_mutate_its_inputs(self):
        plan = self._plan()
        guidance = _guidance(plan, _structure(a="1"))
        selection = select_learned_response_pattern(plan, guidance).to_dict()
        before = copy.deepcopy((plan, guidance, selection))
        LearnedResponsePatternBinder().bind(plan, selection, guidance)
        self.assertEqual((plan, guidance, selection), before)

    def test_to_dict_is_a_fresh_copy_each_time(self):
        binding = _bind(self._plan())
        binding.to_dict()["bound_variables"]["a"] = "tampered"
        binding.to_dict()["selected_pattern"]["pattern"]["id"] = "tampered"
        again = binding.to_dict()
        self.assertEqual(again["bound_variables"]["a"], "1")
        self.assertEqual(again["pattern_id"], "p")

    def test_mutating_the_plan_afterwards_does_not_change_a_made_binding(self):
        plan = self._plan()
        binding = _bind(plan)
        plan["variables"]["a"] = "tampered"
        plan["meaning"]["meaning"][RESPONSE_PATTERNS_KEY][0]["id"] = "tampered"
        self.assertEqual(binding.to_dict()["bound_variables"]["a"], "1")
        self.assertEqual(binding.to_dict()["pattern_id"], "p")

    def test_variables_beyond_the_bound_are_reported_missing_never_bound(self):
        names = [f"v{i}" for i in range(MAX_REQUIRED_VARIABLES + 3)]
        plan = _plan_with([{"id": "p", "required_variables": names}],
                          variables={n: n.upper() for n in names})
        result = _bound(plan)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(len(result["bound_variables"]), MAX_REQUIRED_VARIABLES)
        self.assertEqual(result["missing_variables"], names[MAX_REQUIRED_VARIABLES:])
        self.assertEqual(list(result["bound_variables"]), names[:MAX_REQUIRED_VARIABLES])

    def test_within_the_bound_nothing_is_truncated(self):
        names = [f"v{i}" for i in range(MAX_REQUIRED_VARIABLES)]
        plan = _plan_with([{"id": "p", "required_variables": names}],
                          variables={n: "x" for n in names})
        result = _bound(plan)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["status"], STATUS_RESOLVED)

    def test_a_selection_truncation_is_carried_forward(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        selection = select_learned_response_pattern(plan).to_dict()
        selection["truncated"] = True
        self.assertTrue(LearnedResponsePatternBinder().bind(plan, selection).truncated)


# ----------------------------------------------------------------------
class TestBinderInputs(unittest.TestCase):
    def test_it_accepts_a_plan_dict_a_context_and_its_dict(self):
        plan_dict = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        context = build_generation_context(plan_dict)
        for source in (plan_dict, context, context.to_dict()):
            with self.subTest(source=type(source).__name__):
                selection = select_learned_response_pattern(source)
                result = LearnedResponsePatternBinder().bind(source, selection).to_dict()
                self.assertEqual(result["status"], STATUS_RESOLVED)
                self.assertEqual(result["bound_variables"], {"a": "x"})

    def test_a_selection_object_or_its_dict_are_both_honored(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        selection = select_learned_response_pattern(plan)
        as_object = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        as_dict = LearnedResponsePatternBinder().bind(plan, selection.to_dict()).to_dict()
        self.assertEqual(as_object, as_dict)

    def test_an_explicit_guidance_object_or_dict_is_honored(self):
        plan = _plan_with([{"id": "p", "template": "{{topic}}"}])
        guidance = _guidance(plan, _structure(topic="python"))
        selection = select_learned_response_pattern(plan, guidance)
        result = LearnedResponsePatternBinder().bind(plan, selection, guidance).to_dict()
        self.assertEqual(result["bound_variables"], {"topic": "python"})
        without = LearnedResponsePatternBinder().bind(plan, selection).to_dict()
        self.assertEqual(without["status"], STATUS_UNRESOLVED)

    def test_a_value_of_the_wrong_type_raises_type_error(self):
        for bad in (None, 5, "plan", ["plan"]):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    LearnedResponsePatternBinder().bind(bad)

    def test_the_binding_is_a_binding_object_and_json_shaped(self):
        binding = _bind(_plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"}))
        self.assertIsInstance(binding, LearnedResponsePatternBinding)
        self.assertTrue(binding.resolved)
        self.assertFalse(binding.unresolved or binding.ambiguous or binding.not_found)
        json.dumps(binding.to_dict(), ensure_ascii=False)
        self.assertIn("LearnedResponsePatternBinding", repr(binding))


# ----------------------------------------------------------------------
class TestRealPipelineBinding(_PipelineCase):
    """Real Understanding Engine + real stores; response patterns taught
    through the existing operations."""

    def _binding(self, text, **context):
        return response_pattern_binding_from_understanding(
            self.understand(text, **context)).to_dict()

    def test_a_sentence_pattern_variable_extracted_from_the_message_is_bound(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"], "template": "About {{topic}}."}]})
        result = self._binding("what is python")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"], {"topic": "python"})
        self.assertEqual(result["pattern_id"], "answer_question")
        self.assertEqual(result["original_message"], "what is python")
        self.assertEqual(result["language"], "english")

    def test_a_placeholder_the_message_never_supplied_is_missing(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"],
             "template": "About {{topic}} for {{audience}}."}]})
        result = self._binding("what is python")
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["bound_variables"], {"topic": "python"})
        self.assertEqual(result["missing_variables"], ["audience"])

    def test_several_extracted_variables_are_all_bound(self):
        self.teach("{{who}} gave {{what}} to {{whom}}", meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "gift", "template": "{{who}}/{{what}}/{{whom}}"}]})
        result = self._binding("sara gave tea to bob")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"], {"who": "sara", "what": "tea", "whom": "bob"})

    def test_persian_pattern_with_language_locale_and_variable(self):
        self.teach(PREFERENCE_PATTERN, language="fa", locale="fa-IR", meaning={
            RESPONSE_PATTERNS_KEY: [
                {"id": "ask_why", "language": "fa", "locale": "fa-IR",
                 "template": "چرا {{X}} را دوست داری؟"}]})
        self.bind_meaning(PREFERENCE_PATTERN, "express_preference", language="fa")
        result = self._binding("من چای را دوست دارم", requested_language="fa")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"], {"X": "چای"})
        self.assertEqual(result["original_message"], "من چای را دوست دارم")
        self.assertEqual((result["language"], result["locale"]), ("persian", "fa-IR"))
        self.assertEqual(result["meaning"]["meaning_name"], "express_preference")
        self.assertEqual(result["selected_pattern"]["pattern"]["template"],
                         "چرا {{X}} را دوست داری؟")

    def test_a_pattern_taught_on_a_bound_meaning_without_variables(self):
        self.teach_meaning("greeting", [{"id": "greet_back", "template": "Good morning!"}])
        self.teach(GREETING_PATTERN)
        self.bind_meaning(GREETING_PATTERN, "greeting")
        result = self._binding("good morning")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["reason"], REASON_NO_VARIABLES_REQUIRED)
        self.assertEqual(result["bound_variables"], {})

    def test_a_routed_learned_expression_variable(self):
        self.items.learn_item("en", "word", "python", meaning={
            "gloss": "a language", RESPONSE_PATTERNS_KEY: [
                {"id": "about_python", "template": "{{lang}}",
                 "variable_sources": {"lang": "expression"}}]})
        result = self._binding("I like python")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["bound_variables"], {"lang": "python"})

    def test_two_equally_valid_patterns_stay_ambiguous(self):
        self.teach_meaning("greeting", [{"id": "one", "template": "{{a}}"},
                                        {"id": "two", "template": "{{a}}"}])
        self.teach(GREETING_PATTERN)
        self.bind_meaning(GREETING_PATTERN, "greeting")
        result = self._binding("good morning")
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual([c["pattern_id"] for c in result["candidates"]], ["one", "two"])
        self.assertEqual(result["bound_variables"], {})

    def test_two_bound_meanings_stay_ambiguous(self):
        self.teach("thanks {{who}}")
        self.teach_meaning("gratitude", [{"id": "you_are_welcome", "template": "{{who}}"}])
        self.teach_meaning("farewell", [{"id": "goodbye_back", "template": "{{who}}"}])
        self.bind_meaning("thanks {{who}}", "gratitude")
        self.bind_meaning("thanks {{who}}", "farewell")
        result = self._binding("thanks bob")
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertEqual(result["bound_variables"], {})

    def test_nothing_taught_is_not_found(self):
        self.teach(GREETING_PATTERN)
        self.bind_meaning(GREETING_PATTERN, "greeting")
        result = self._binding("good morning")
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["original_message"], "good morning")

    def test_a_message_matching_nothing_is_not_found(self):
        self.teach_meaning("greeting", [{"id": "greet_back", "template": "{{a}}"}])
        self.assertEqual(self._binding("qwerty zzznoxyzzz unmapped concept")["status"],
                         STATUS_NOT_FOUND)

    def test_binding_matches_the_selection_it_was_made_from(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"]}]})
        understanding = self.understand("what is python")
        selection = response_pattern_selection_from_understanding(understanding).to_dict()
        binding = response_pattern_binding_from_understanding(understanding).to_dict()
        self.assertEqual(binding["selected_pattern"], selection["selected_pattern"])
        self.assertEqual((binding["confidence"], binding["source"]),
                         (selection["confidence"], selection["source"]))

    def test_binding_reads_no_store_at_all(self):
        # bounded: a pure function of the plan/guidance/selection in hand -
        # no language-learning table, memory or knowledge query is made
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "template": "{{topic}}"}]})
        for index in range(30):
            self.items.learn_item("en", "meaning", f"other_{index}", meaning={
                RESPONSE_PATTERNS_KEY: [{"id": f"unrelated_{index}", "template": "{{z}}"}]})
        understanding = self.understand("what is python")
        with mock.patch.object(self.memory, "query", wraps=self.memory.query) as query, \
                mock.patch.object(self.memory, "query_one", wraps=self.memory.query_one) as one, \
                mock.patch.object(self.memory, "_run", wraps=self.memory._run) as run:
            binding = response_pattern_binding_from_understanding(understanding).to_dict()
            generation_context_from_understanding(understanding)
            generation_request_from_understanding(understanding)
        self.assertEqual((query.call_count, one.call_count, run.call_count), (0, 0, 0))
        self.assertEqual(binding["bound_variables"], {"topic": "python"})
        self.assertNotIn("unrelated", json.dumps(binding))

    def test_binding_writes_nothing_to_the_language_learning_store(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "template": "{{topic}}"}]})
        understanding = self.understand("what is python")
        before = self.memory.query("SELECT * FROM language_learning_items ORDER BY id")
        events_before = len(self.memory.query("SELECT * FROM learning_events"))
        for _ in range(3):
            response_pattern_binding_from_understanding(understanding)
            generation_context_from_understanding(understanding)
        self.assertEqual(self.memory.query("SELECT * FROM language_learning_items ORDER BY id"),
                         before)
        self.assertEqual(len(self.memory.query("SELECT * FROM learning_events")), events_before)

    def test_a_live_response_plan_object_binds_like_its_dict(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"], "template": "{{topic}}"}]})
        understanding = self.understand("what is python")
        plan_object = self.planner.plan(understanding)
        self.assertIsInstance(plan_object, ResponsePlan)
        guidance = language_guidance_from_understanding(understanding)
        selection = select_learned_response_pattern(plan_object, guidance)
        from_object = bind_learned_response_pattern(plan_object, selection, guidance).to_dict()
        from_dict = bind_learned_response_pattern(
            plan_object.to_dict(), selection, guidance).to_dict()
        self.assertEqual(from_object, from_dict)
        self.assertEqual(from_object["bound_variables"], {"topic": "python"})

    def test_repeated_real_binding_is_identical(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "template": "{{topic}}"}]})
        understanding = self.understand("what is python")
        first = response_pattern_binding_from_understanding(understanding).to_dict()
        for _ in range(10):
            self.assertEqual(
                response_pattern_binding_from_understanding(understanding).to_dict(), first)

    def test_no_understanding_plan_means_no_binding(self):
        class _NoPlan:
            response_plan = None
            learned_sentence_structure = None
        self.assertIsNone(response_pattern_binding_from_understanding(_NoPlan()))


# ----------------------------------------------------------------------
class TestCompatibleWithResponseGenerationContext(_PipelineCase):
    """13. The binding rides on the existing ResponseGenerationContext,
    after selection, without changing anything already there."""

    def _taught(self):
        self.teach(QUESTION_PATTERN, meaning={
            "response_action": "answer", RESPONSE_PATTERNS_KEY: [
                {"id": "answer_question", "variables": ["topic"], "template": "About {{topic}}."}]})
        return self.understand("what is python")

    def test_the_context_carries_the_binding(self):
        context = generation_context_from_understanding(self._taught())
        self.assertIsInstance(context, ResponseGenerationContext)
        self.assertEqual(context.response_pattern_binding["status"], STATUS_RESOLVED)
        self.assertEqual(context.response_pattern_binding["bound_variables"],
                         {"topic": "python"})
        self.assertEqual(context.to_dict()["response_pattern_binding"],
                         context.response_pattern_binding)

    def test_the_contexts_binding_equals_the_binders_own(self):
        understanding = self._taught()
        context = generation_context_from_understanding(understanding)
        self.assertEqual(context.response_pattern_binding,
                         response_pattern_binding_from_understanding(understanding).to_dict())

    def test_the_binding_is_made_from_the_contexts_own_selection(self):
        context = generation_context_from_understanding(self._taught())
        self.assertEqual(context.response_pattern_binding["selected_pattern"],
                         context.response_pattern_selection["selected_pattern"])

    def test_every_existing_context_field_is_unchanged(self):
        understanding = self._taught()
        context = generation_context_from_understanding(understanding)
        plan = understanding.response_plan
        data = context.to_dict()
        self.assertEqual(data["original_message"], "what is python")
        self.assertEqual(data["status"], plan["status"])
        self.assertEqual(data["response_action"], plan["response_action"])
        self.assertEqual(data["matched_pattern"], plan["matched_pattern"])
        self.assertEqual(data["variables"], plan["variables"])
        self.assertEqual(data["language_guidance"],
                         language_guidance_from_understanding(understanding).to_dict())
        self.assertEqual(data["response_pattern_selection"],
                         response_pattern_selection_from_understanding(understanding).to_dict())
        for key in ("meaning", "meaning_candidates", "active_topic", "references", "context",
                    "language", "locale", "unresolved_requirements"):
            self.assertIn(key, data)

    def test_the_binding_does_not_change_context_status_or_action(self):
        understanding = self._taught()
        context = generation_context_from_understanding(understanding)
        self.assertEqual(context.status, understanding.response_plan["status"])
        self.assertEqual(context.response_action, understanding.response_plan["response_action"])

    def test_a_context_with_no_learned_response_pattern_carries_not_found(self):
        self.teach(GREETING_PATTERN)
        self.bind_meaning(GREETING_PATTERN, "greeting")
        context = generation_context_from_understanding(self.understand("good morning"))
        self.assertEqual(context.response_pattern_binding["status"], STATUS_NOT_FOUND)

    def test_an_unresolved_binding_rides_on_the_context(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "p", "template": "{{topic}} {{audience}}"}]})
        context = generation_context_from_understanding(self.understand("what is python"))
        self.assertEqual(context.response_pattern_binding["status"], STATUS_UNRESOLVED)
        self.assertEqual(context.response_pattern_binding["missing_variables"], ["audience"])
        self.assertEqual(context.response_pattern_binding["bound_variables"], {"topic": "python"})

    def test_an_ambiguous_selection_is_carried_unbound(self):
        self.teach_meaning("greeting", [{"id": "one"}, {"id": "two"}])
        self.teach(GREETING_PATTERN)
        self.bind_meaning(GREETING_PATTERN, "greeting")
        context = generation_context_from_understanding(self.understand("good morning"))
        self.assertEqual(context.response_pattern_selection["status"], SEL_AMBIGUOUS)
        self.assertEqual(context.response_pattern_binding["status"], STATUS_AMBIGUOUS)

    def test_a_context_built_by_hand_without_a_binding_still_works(self):
        context = ResponseGenerationContext(
            original_message="hi", status=PLAN_RESOLVED, response_action=None, meaning=None,
            meaning_candidates=[], matched_pattern=None, variables={}, active_topic=None,
            references=[], context=None, language="english", locale=None,
            unresolved_requirements=[])
        self.assertIsNone(context.response_pattern_binding)
        self.assertIsNone(context.to_dict()["response_pattern_binding"])

    def test_a_plan_dict_builds_the_same_context_as_a_plan_object(self):
        plan = _plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"})
        first = build_generation_context(plan).to_dict()
        self.assertEqual(build_generation_context(copy.deepcopy(plan)).to_dict(), first)
        self.assertEqual(first["response_pattern_binding"]["bound_variables"], {"a": "x"})

    def test_the_bad_plan_type_contract_of_the_context_builder_is_unchanged(self):
        with self.assertRaises(TypeError):
            build_generation_context("not a plan")

    def test_the_context_binding_is_an_independent_copy(self):
        understanding = self._taught()
        context = generation_context_from_understanding(understanding)
        context.response_pattern_binding["status"] = "TAMPERED"
        context.to_dict()["response_pattern_binding"]["bound_variables"]["topic"] = "x"
        again = generation_context_from_understanding(understanding)
        self.assertEqual(again.response_pattern_binding["status"], STATUS_RESOLVED)
        self.assertEqual(again.response_pattern_binding["bound_variables"], {"topic": "python"})

    def test_the_context_is_json_shaped(self):
        json.dumps(generation_context_from_understanding(self._taught()).to_dict(),
                   ensure_ascii=False)


# ----------------------------------------------------------------------
class TestCompatibleWithResponseGenerationRequest(_PipelineCase):
    """14. The binding reaches `ResponseGenerationRequest` and
    `BackendGenerationRequest` unchanged; nothing downstream changes."""

    def _taught(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"], "template": "About {{topic}}."}]})
        return self.understand("what is python")

    def test_the_backend_generation_request_carries_the_binding_unchanged(self):
        understanding = self._taught()
        request = generation_request_from_understanding(understanding)
        self.assertIsInstance(request, BackendGenerationRequest)
        context = generation_context_from_understanding(understanding)
        self.assertEqual(request.response_pattern_binding, context.response_pattern_binding)
        self.assertEqual(request.to_dict()["response_pattern_binding"]["bound_variables"],
                         {"topic": "python"})

    def test_build_generation_request_carries_it_from_a_context_or_its_dict(self):
        context = generation_context_from_understanding(self._taught())
        for source in (context, context.to_dict()):
            request = build_generation_request(source)
            self.assertEqual(request.response_pattern_binding, context.response_pattern_binding)

    def test_the_request_accessors_expose_the_binding(self):
        request = ResponseGenerationRequest(self._taught())
        self.assertEqual(request.generation_context["response_pattern_binding"]["status"],
                         STATUS_RESOLVED)
        self.assertEqual(request.generation_request["response_pattern_binding"]["status"],
                         STATUS_RESOLVED)
        self.assertEqual(request.generation_context["response_pattern_binding"],
                         request.generation_request["response_pattern_binding"])

    def test_the_request_still_carries_the_selection_and_guidance(self):
        understanding = self._taught()
        data = generation_request_from_understanding(understanding).to_dict()
        self.assertEqual(data["response_pattern_selection"]["status"], SEL_RESOLVED)
        self.assertEqual(data["language_guidance"],
                         language_guidance_from_understanding(understanding).to_dict())
        self.assertEqual(data["sentence_structure"], understanding.learned_sentence_structure)

    def test_every_existing_request_field_is_unchanged(self):
        understanding = self._taught()
        data = generation_request_from_understanding(understanding).to_dict()
        plan = understanding.response_plan
        self.assertEqual(data["status"], plan["status"])
        self.assertEqual(data["matched_pattern"], plan["matched_pattern"])
        for key in ("original_message", "response_action", "meaning", "meaning_candidates",
                    "variables", "active_topic", "references", "context", "language", "locale",
                    "unresolved_requirements"):
            self.assertIn(key, data)
        self.assertEqual(data["original_message"], "what is python")

    def test_a_request_built_by_hand_without_a_binding_still_works(self):
        request = BackendGenerationRequest(
            original_message="hi", status=PLAN_RESOLVED, response_action=None, meaning=None,
            meaning_candidates=[], matched_pattern=None, sentence_structure=None, variables={},
            active_topic=None, references=[], context=None, language="english", locale=None,
            unresolved_requirements=[])
        self.assertIsNone(request.response_pattern_binding)
        self.assertIsNone(request.to_dict()["response_pattern_binding"])

    def test_the_request_binding_is_an_independent_copy(self):
        understanding = self._taught()
        request = generation_request_from_understanding(understanding)
        request.response_pattern_binding["status"] = "TAMPERED"
        request.to_dict()["response_pattern_binding"]["bound_variables"]["topic"] = "x"
        again = generation_request_from_understanding(understanding)
        self.assertEqual(again.response_pattern_binding["status"], STATUS_RESOLVED)
        self.assertEqual(again.response_pattern_binding["bound_variables"], {"topic": "python"})

    def test_no_plan_means_no_request_and_no_binding(self):
        class _NoPlan:
            response_plan = None
            learned_sentence_structure = None
        self.assertIsNone(generation_request_from_understanding(_NoPlan()))
        self.assertIsNone(generation_context_from_understanding(_NoPlan()))
        self.assertIsNone(ResponseGenerationRequest(_NoPlan()).generation_context)

    def test_the_deterministic_backend_still_defers_and_generates_no_text(self):
        result = self.backend.generate_response(ResponseGenerationRequest(self._taught()))
        self.assertEqual(result.status, STATUS_DEFERRED)
        self.assertIsNone(result.response_text)


# ----------------------------------------------------------------------
class TestCoreIntegrationUnaffected(unittest.TestCase):
    """Regression: Core's existing understand/generate path is unaffected
    by the presence of the binding."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = Core(memory_db_path=os.path.join(self._tmp.name, "core.db"),
                         skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        self.assertEqual(
            self.core.teach_sentence_pattern("en", GREETING_PATTERN).status, STATUS_CREATED)
        bound = self.core.bind_pattern_meaning("en", GREETING_PATTERN, "greeting")
        self.assertTrue(bound.success, bound.errors)

    def _teach_response_pattern(self, template="Good morning, {{name}}!"):
        self.core.learn_language_item("en", "meaning", "greeting", meaning={
            "response_action": "greet",
            RESPONSE_PATTERNS_KEY: [{"id": "greet_back", "template": template}]})

    def _context(self, text="good morning"):
        understanding = self.core.understand_language(text)
        return ResponseGenerationRequest(understanding, context=self.core.context)

    def test_generation_context_via_core_includes_the_binding(self):
        self._teach_response_pattern("Good morning!")
        ctx = self._context().generation_context
        self.assertEqual(ctx["response_pattern_binding"]["status"], STATUS_RESOLVED)
        self.assertEqual(ctx["response_pattern_binding"]["pattern_id"], "greet_back")
        # every prior field is still exactly as before
        self.assertEqual(ctx["response_action"], "greet")
        self.assertEqual(ctx["original_message"], "good morning")
        self.assertEqual(ctx["response_pattern_selection"]["status"], SEL_RESOLVED)

    def test_a_missing_variable_is_reported_via_core(self):
        self._teach_response_pattern()
        ctx = self._context().generation_context
        self.assertEqual(ctx["response_pattern_binding"]["status"], STATUS_UNRESOLVED)
        self.assertEqual(ctx["response_pattern_binding"]["missing_variables"], ["name"])
        self.assertEqual(ctx["response_pattern_binding"]["bound_variables"], {})

    def test_generation_request_via_core_includes_the_binding(self):
        self._teach_response_pattern("Good morning!")
        req = self._context().generation_request
        self.assertEqual(req["response_pattern_binding"]["status"], STATUS_RESOLVED)
        self.assertEqual(req["response_pattern_binding"]["pattern_id"], "greet_back")

    def test_behavior_is_preserved_when_no_response_pattern_is_taught(self):
        ctx = self._context().generation_context
        self.assertEqual(ctx["response_pattern_binding"]["status"], STATUS_NOT_FOUND)
        self.assertEqual(ctx["response_pattern_selection"]["status"], SEL_NOT_FOUND)
        self.assertEqual(ctx["response_action"], "greet")
        self.assertEqual(ctx["status"], "RESOLVED")

    def test_deterministic_generation_is_still_deferred_with_no_text(self):
        self._teach_response_pattern()
        understanding = self.core.understand_language("good morning")
        response = self.core.generate_language_response(understanding)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)

    def test_an_unrelated_message_binds_nothing(self):
        self._teach_response_pattern()
        ctx = self._context("qwerty zzznoxyzzz unmapped concept").generation_context
        self.assertEqual(ctx["response_pattern_binding"]["status"], STATUS_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
