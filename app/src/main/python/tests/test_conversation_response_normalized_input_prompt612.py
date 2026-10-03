"""
Tests for Prompt 612 - normalized_input on ConversationResponse.

Continues the existing `normalized_input` propagation:

    LanguageUnderstandingResult.normalized_input   (Prompt 609)
      -> ResponsePlan.normalized_input             (Prompt 609)
      -> ResponseGenerationContext.normalized_input(Prompt 610)
      -> ResponseGenerationOutcome.normalized_input(Prompt 611)
      -> ConversationResponse.normalized_input     (this prompt)

`build_conversation_response()` (language_intelligence/
conversation_response.py) reads the value straight from the SAME
`outcome.normalized_input` `correction_application_result_usable`
already uses the safe-forwarding pattern for (Prompt 578) - never a
second normalization, never derived from `original_message`/
`original_input` again.

Run directly:
    python -m unittest tests.test_conversation_response_normalized_input_prompt612 -v
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
    build_response_generation_outcome,
)
from language_intelligence.conversation_response import (
    ConversationResponse, build_conversation_response,
)

GREETING_PATTERN = "good morning"


class _PlanCase(unittest.TestCase):
    """Same composition test_response_generation_outcome_normalized_input_
    prompt611.py's `_PlanCase` builds - a real Understanding Engine, real
    Prompt 416-424 stores, a deterministic backend wired to them, and a
    LanguageIntelligenceCore (which plans every understanding it returns,
    Prompt 425)."""

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


class TestNormalizedInputReachesConversationResponse(_PlanCase):
    """1. normalized_input reaches ConversationResponse from a real
    request's outcome."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_normalized_input_is_present_on_the_response(self):
        understanding, request = self.request_for("  good   morning  ")
        response = build_conversation_response(self.deferred_result(), request=request)
        self.assertTrue(hasattr(response, "normalized_input"))
        self.assertEqual(response.normalized_input, "good morning")

    def test_normalized_input_is_present_in_to_dict(self):
        understanding, request = self.request_for("  good   morning  ")
        response = build_conversation_response(self.deferred_result(), request=request)
        self.assertEqual(response.to_dict()["normalized_input"], "good morning")


class TestExactValuePreservationFromOutcome(_PlanCase):
    """2. The value is exactly `outcome.normalized_input` - never
    recomputed independently by this module."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_matches_the_outcome_when_supplied_explicitly(self):
        understanding, request = self.request_for("  good   morning  ")
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        response = build_conversation_response(
            self.deferred_result(), request=request, outcome=outcome)
        self.assertEqual(response.normalized_input, outcome.normalized_input)

    def test_matches_the_outcome_when_built_internally(self):
        understanding, request = self.request_for("  good   morning  ")
        outcome = build_response_generation_outcome(self.deferred_result(), request=request)
        response = build_conversation_response(self.deferred_result(), request=request)
        self.assertEqual(response.normalized_input, outcome.normalized_input)
        self.assertEqual(response.normalized_input, understanding.normalized_input)


class TestNonePropagation(_PlanCase):
    """3. None propagates safely: no request, or an outcome that itself
    carries none."""

    def test_no_request_means_no_normalized_input(self):
        response = build_conversation_response(self.deferred_result())
        self.assertIsNone(response.normalized_input)

    def test_none_stays_none_in_to_dict(self):
        response = build_conversation_response(self.deferred_result())
        self.assertIsNone(response.to_dict()["normalized_input"])


class TestOriginalInputRemainsUnchanged(_PlanCase):
    """4. original_message/original_input on the request's own context is
    never touched or conflated with normalized_input."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_original_message_on_context_is_unaffected(self):
        text = "  good   morning  "
        understanding, request = self.request_for(text)
        before = request.generation_context["original_message"]
        build_conversation_response(self.deferred_result(), request=request)
        after = request.generation_context["original_message"]
        self.assertEqual(before, after)
        self.assertEqual(before, text)

    def test_original_and_normalized_differ_on_the_response(self):
        text = "  good   morning  "
        understanding, request = self.request_for(text)
        response = build_conversation_response(self.deferred_result(), request=request)
        self.assertEqual(request.generation_context["original_message"], text)
        self.assertNotEqual(request.generation_context["original_message"],
                             response.normalized_input)


class TestAlreadyNormalizedTextUnchanged(_PlanCase):
    """5. Text that is already normalized is not transformed again."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_already_normalized_text_passes_through(self):
        understanding, request = self.request_for("good morning")
        response = build_conversation_response(self.deferred_result(), request=request)
        self.assertEqual(response.normalized_input, "good morning")
        self.assertEqual(response.normalized_input, understanding.normalized_input)


class TestLegacyDirectConstructionRemainsSafe(unittest.TestCase):
    """6. Direct construction of ConversationResponse (bypassing
    build_conversation_response), the way existing callers/tests
    predating this prompt already do, keeps working and defaults safely."""

    def test_legacy_construction_without_normalized_input(self):
        response = ConversationResponse(
            response_text="hi", status="SUCCESS",
            backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.normalized_input)
        self.assertIsNone(response.to_dict()["normalized_input"])

    def test_legacy_construction_with_all_prior_kwargs_still_works(self):
        response = ConversationResponse(
            response_text=None, status="FAILED",
            backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK, language="english", locale=None,
            failure_reason={"error_code": "x", "inference_status": "y", "reason": "z"},
            fallback_used=False, metadata=None, valid=True, validation_issues=(),
            generation_status="MODEL_FAILED", reason="failed",
            generation_backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK,
            fallback_backend_kind=None, selected_backend_kind=None,
            inference_status=None, error_code="x",
            correction_application_result_usable=False)
        self.assertIsNone(response.normalized_input)


class TestLegacyOutcomeWithoutTheFieldRemainsSafe(unittest.TestCase):
    """7. An outcome built before Prompt 611 (no `normalized_input`
    attribute at all) still produces a safe ConversationResponse - the
    SAME `getattr(..., None)` posture `correction_application_result_usable`
    (Prompt 578) already uses for a pre-Prompt-577 outcome."""

    class _LegacyOutcome:
        """Deliberately has no `normalized_input` attribute, mirroring a
        hand-built or pre-Prompt-611 outcome object."""

        def __init__(self):
            self.status = "UNRESOLVED"
            self.generated_text = None
            self.backend_kind = BACKEND_KIND_DETERMINISTIC_FALLBACK
            self.language = None
            self.locale = None
            self.failure_reason = None
            self.fallback_used = False
            self.metadata = None
            self.used_verified_correction = False
            self.correction_application_result_usable = False

    def test_legacy_outcome_yields_none_normalized_input(self):
        result = ResponseGenerationResult(
            status=STATUS_DEFERRED, backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        legacy_outcome = self._LegacyOutcome()
        response = build_conversation_response(result, outcome=legacy_outcome)
        self.assertIsNone(response.normalized_input)
        self.assertIsNone(response.to_dict()["normalized_input"])


class TestNoSecondNormalizationOccurs(_PlanCase):
    """8. A message whose whitespace is not yet collapsed proves the
    value on the response is exactly the outcome's own value - never
    re-derived from `original_message`/`original_input` a second time by
    this module (which would, coincidentally, produce the same
    whitespace-collapse here and mask a duplicate implementation)."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_response_value_matches_understandings_own_normalization(self):
        understanding, request = self.request_for("good   \t morning")
        self.assertEqual(understanding.normalized_input, "good morning")
        response = build_conversation_response(self.deferred_result(), request=request)
        self.assertEqual(response.normalized_input, understanding.normalized_input)
        self.assertEqual(response.normalized_input, request.generation_context["normalized_input"])


if __name__ == "__main__":
    unittest.main()
