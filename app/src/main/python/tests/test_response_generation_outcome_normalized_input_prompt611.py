"""
Tests for Prompt 611 - normalized_input on ResponseGenerationOutcome.

Continues the existing `normalized_input` propagation:

    LanguageUnderstandingResult.normalized_input   (Prompt 609)
      -> ResponsePlan.normalized_input             (Prompt 609)
      -> ResponseGenerationContext.normalized_input(Prompt 610)
      -> ResponseGenerationOutcome.normalized_input(this prompt)

`build_response_generation_outcome()` (language_intelligence/
response_generation_outcome.py) reads the value straight from the
SAME `request.generation_context` dict `language`/`locale` already
come from - never a second normalization, never derived from
`original_message`/`original_input` again.

Run directly:
    python -m unittest tests.test_response_generation_outcome_normalized_input_prompt611 -v
"""

import os
import sys
import tempfile
import unittest

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
from language_intelligence.response_planning import ResponsePlanner
from language_intelligence.backend import BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED,
)
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome,
)

GREETING_PATTERN = "good morning"


class _PlanCase(unittest.TestCase):
    """Same composition test_response_generation_outcome.py's `_PlanCase`
    builds - a real Understanding Engine, real Prompt 416-424 stores, a
    deterministic backend wired to them, and a LanguageIntelligenceCore
    (which plans every understanding it returns, Prompt 425)."""

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

    def teach_and_bind(self, pattern, meaning, language="en", **kwargs):
        result = self.teacher.teach(language, pattern, **kwargs)
        self.assertEqual(result.status, STATUS_CREATED, result.errors)
        bound = self.binder.bind(language, pattern, meaning, **kwargs)
        self.assertTrue(bound.success, bound.errors)
        return bound

    def request_for(self, text, **context):
        understanding = self.lic.understand(text, **context)
        return understanding, ResponseGenerationRequest(understanding, context=context.get("context"))

    def deferred_result(self):
        return ResponseGenerationResult(
            status=STATUS_DEFERRED, backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestNormalizedInputReachesTheOutcome(_PlanCase):
    """1. normalized_input reaches the outcome from a real request's
    generation context."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_normalized_input_is_present_on_the_outcome(self):
        understanding, request = self.request_for("  good   morning  ")
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        self.assertTrue(hasattr(outcome, "normalized_input"))
        self.assertEqual(outcome.normalized_input, "good morning")

    def test_normalized_input_is_present_in_to_dict(self):
        understanding, request = self.request_for("  good   morning  ")
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        self.assertEqual(outcome.to_dict()["normalized_input"], "good morning")


class TestExactValuePreservationFromGenerationContext(_PlanCase):
    """2. The value is exactly `request.generation_context["normalized_input"]`
    - never recomputed independently by this module."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_matches_the_requests_generation_context(self):
        understanding, request = self.request_for("  good   morning  ")
        expected = request.generation_context["normalized_input"]
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        self.assertEqual(outcome.normalized_input, expected)

    def test_matches_the_plan_and_understanding(self):
        understanding, request = self.request_for("  good   morning  ")
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        self.assertEqual(outcome.normalized_input, request.response_plan["normalized_input"])
        self.assertEqual(outcome.normalized_input, understanding.normalized_input)


class TestNonePropagation(_PlanCase):
    """3. None propagates safely: no request, or a request whose plan
    carries none."""

    def test_no_request_means_no_normalized_input(self):
        outcome = build_response_generation_outcome(self.deferred_result())
        self.assertIsNone(outcome.normalized_input)

    def test_none_stays_none_in_to_dict(self):
        outcome = build_response_generation_outcome(self.deferred_result())
        self.assertIsNone(outcome.to_dict()["normalized_input"])


class TestOriginalInputRemainsUnchanged(_PlanCase):
    """4. original_message/original_input on the request's own plan and
    context is never touched or conflated with normalized_input."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_original_message_on_context_is_unaffected(self):
        text = "  good   morning  "
        understanding, request = self.request_for(text)
        before = request.generation_context["original_message"]
        build_response_generation_outcome(self.deferred_result(), request=request)
        after = request.generation_context["original_message"]
        self.assertEqual(before, after)
        self.assertEqual(before, text)

    def test_original_and_normalized_differ_on_the_outcome_path(self):
        text = "  good   morning  "
        understanding, request = self.request_for(text)
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        self.assertEqual(request.generation_context["original_message"], text)
        self.assertNotEqual(request.generation_context["original_message"],
                             outcome.normalized_input)


class TestAlreadyNormalizedTextUnchanged(_PlanCase):
    """5. Text that is already normalized is not transformed again."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_already_normalized_text_passes_through(self):
        understanding, request = self.request_for("good morning")
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        self.assertEqual(outcome.normalized_input, "good morning")
        self.assertEqual(outcome.normalized_input, understanding.normalized_input)


class TestLegacyDirectConstructionRemainsSafe(unittest.TestCase):
    """6. Direct construction of ResponseGenerationOutcome (bypassing
    build_response_generation_outcome), the way existing callers/tests
    predating this prompt already do, keeps working and defaults safely."""

    def test_legacy_construction_without_normalized_input(self):
        outcome = ResponseGenerationOutcome(
            status="SUCCESS", generated_text="hi",
            backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(outcome.normalized_input)
        self.assertIsNone(outcome.to_dict()["normalized_input"])

    def test_legacy_construction_with_all_prior_kwargs_still_works(self):
        outcome = ResponseGenerationOutcome(
            status="FAILED", generated_text=None,
            backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK, language="english", locale=None,
            failure_reason={"error_code": "x", "inference_status": "y", "reason": "z"},
            fallback_used=False, metadata=None, used_verified_correction=False,
            correction_application_result_usable=False)
        self.assertIsNone(outcome.normalized_input)


class TestNoSecondNormalizationOccurs(_PlanCase):
    """7. A message whose whitespace is not yet collapsed proves the
    value on the outcome is exactly the request's own generation-context
    value - never re-derived from `original_message`/`original_input` a
    second time by this module (which would, coincidentally, produce the
    same whitespace-collapse here and mask a duplicate implementation)."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_outcome_value_matches_understandings_own_normalization(self):
        understanding, request = self.request_for("good   \t morning")
        self.assertEqual(understanding.normalized_input, "good morning")
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        self.assertEqual(outcome.normalized_input, understanding.normalized_input)
        self.assertEqual(outcome.normalized_input, request.generation_context["normalized_input"])


if __name__ == "__main__":
    unittest.main()
