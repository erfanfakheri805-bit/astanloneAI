"""
Tests for Prompt 428 - Structured Response-Generation Outcome.

`build_response_generation_outcome()` (language_intelligence/
response_generation_outcome.py) turns an already-produced
`ResponseGenerationResult` (response_generation.py) into a small,
additive `ResponseGenerationOutcome` with exactly four deterministic
statuses (SUCCESS / FALLBACK / FAILED / UNRESOLVED). It never generates
text itself, never calls a backend, and never mutates the result or
request it is given.

Unit-level tests build `ResponseGenerationResult` objects directly (the
same values a real backend already produces - see response_generation.py
and local_model_mapping.py) to exercise every status/field in isolation.
Integration-level tests drive the real `LocalLanguageModelBackend` /
`DeterministicFallbackBackend` / `LanguageIntelligenceCore` machinery
(reusing the existing Prompt 409/413 test doubles) so SUCCESS, FALLBACK
and FAILED are also shown to happen from the real, unmodified generation
flow - never a parallel one built just for this test.

Run directly:
    python -m unittest tests.test_response_generation_outcome -v
"""

import copy
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
from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult,
    STATUS_DEFERRED, STATUS_GENERATED, STATUS_NOT_IMPLEMENTED, STATUS_MODEL_FAILED,
    STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
)
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome,
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED, ALL_OUTCOME_STATUSES,
)
from language_intelligence.inference import STATUS_SUCCESS as INF_SUCCESS

from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime

QUESTION_PATTERN = "what is {{topic}}"


# ----------------------------------------------------------------------
# Unit-level: build_response_generation_outcome() over hand-built results
# ----------------------------------------------------------------------
class TestSuccessResult(unittest.TestCase):
    """1. A real generated result maps to SUCCESS."""

    def test_status_is_success(self):
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="hello there",
            backend_kind=BACKEND_KIND_LOCAL_MODEL, inference_status=INF_SUCCESS,
        )
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertTrue(outcome.succeeded)
        self.assertFalse(outcome.failed)
        self.assertFalse(outcome.unresolved)

    def test_generated_text_is_preserved_exactly(self):
        for text in ("  leading and trailing  \n", "Zażółć gęślą jaźń — سلام — 你好",
                     "line one\nline two"):
            with self.subTest(text=text):
                result = ResponseGenerationResult(
                    status=STATUS_GENERATED, response_text=text,
                    backend_kind=BACKEND_KIND_LOCAL_MODEL,
                )
                outcome = build_response_generation_outcome(result)
                self.assertEqual(outcome.generated_text, text)

    def test_backend_is_preserved(self):
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="hi", backend_kind=BACKEND_KIND_LOCAL_MODEL,
        )
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_LOCAL_MODEL)

    def test_fallback_used_is_false(self):
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="hi", backend_kind=BACKEND_KIND_LOCAL_MODEL,
        )
        outcome = build_response_generation_outcome(result)
        self.assertFalse(outcome.fallback_used)
        self.assertIsNone(outcome.failure_reason)

    def test_metadata_is_preserved(self):
        metadata = {"model_id": "test-model", "elapsed_seconds": 0.01}
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="hi", backend_kind=BACKEND_KIND_LOCAL_MODEL,
            metadata=metadata,
        )
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.metadata, metadata)
        # Mutating the outcome's own metadata dict must never reach the
        # underlying result's (no shared mutable reference).
        outcome.metadata["model_id"] = "changed"
        self.assertEqual(result.metadata["model_id"], "test-model")


class TestFallbackResult(unittest.TestCase):
    """2. A model failure with a fallback backend marked maps to FALLBACK."""

    def _fallback_result(self, response_text=None):
        return ResponseGenerationResult(
            status=STATUS_MODEL_FAILED, response_text=response_text,
            backend_kind=BACKEND_KIND_LOCAL_MODEL, reason="the local model failed",
            inference_status="timeout", error_code="timed_out",
            fallback_backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK,
        )

    def test_status_is_fallback(self):
        outcome = build_response_generation_outcome(self._fallback_result())
        self.assertEqual(outcome.status, STATUS_FALLBACK)

    def test_fallback_used_is_true(self):
        outcome = build_response_generation_outcome(self._fallback_result())
        self.assertTrue(outcome.fallback_used)

    def test_backend_kind_is_the_fallback_backend(self):
        outcome = build_response_generation_outcome(self._fallback_result())
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_fallback_response_text_is_preserved_when_present(self):
        outcome = build_response_generation_outcome(self._fallback_result("fallback reply text"))
        self.assertEqual(outcome.generated_text, "fallback reply text")

    def test_no_text_is_invented_when_the_fallback_produced_none(self):
        outcome = build_response_generation_outcome(self._fallback_result(None))
        self.assertIsNone(outcome.generated_text)

    def test_failure_reason_is_not_set_on_fallback(self):
        outcome = build_response_generation_outcome(self._fallback_result())
        self.assertIsNone(outcome.failure_reason)


class TestFailedResult(unittest.TestCase):
    """3. A model failure with no fallback available maps to FAILED."""

    def _failed_result(self, status=STATUS_MODEL_FAILED, error_code="timed_out",
                        inference_status="timeout", reason="the model timed out"):
        return ResponseGenerationResult(
            status=status, response_text=None, backend_kind=BACKEND_KIND_LOCAL_MODEL,
            reason=reason, inference_status=inference_status, error_code=error_code,
        )

    def test_status_is_failed(self):
        outcome = build_response_generation_outcome(self._failed_result())
        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertTrue(outcome.failed)

    def test_no_response_is_invented(self):
        outcome = build_response_generation_outcome(self._failed_result())
        self.assertIsNone(outcome.generated_text)

    def test_fallback_used_is_false(self):
        outcome = build_response_generation_outcome(self._failed_result())
        self.assertFalse(outcome.fallback_used)

    def test_failure_reason_preserves_the_underlying_result(self):
        result = self._failed_result(error_code="load_failed", inference_status="model_load_failed",
                                      reason="could not load the model")
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.failure_reason, {
            "error_code": "load_failed",
            "inference_status": "model_load_failed",
            "reason": "could not load the model",
        })

    def test_every_model_failure_status_maps_to_failed_without_a_fallback(self):
        for status in (STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED):
            with self.subTest(status=status):
                outcome = build_response_generation_outcome(self._failed_result(status=status))
                self.assertEqual(outcome.status, STATUS_FAILED)

    def test_backend_is_preserved_on_failure(self):
        outcome = build_response_generation_outcome(self._failed_result())
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_LOCAL_MODEL)


class TestUnresolvedResult(unittest.TestCase):
    """4. STATUS_DEFERRED / STATUS_NOT_IMPLEMENTED map to UNRESOLVED."""

    def test_deferred_maps_to_unresolved(self):
        result = ResponseGenerationResult(
            status=STATUS_DEFERRED, response_text=None,
            backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK,
            reason="the deterministic fallback backend does not generate reply text",
        )
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.status, STATUS_UNRESOLVED)
        self.assertTrue(outcome.unresolved)
        self.assertIsNone(outcome.generated_text)
        self.assertIsNone(outcome.failure_reason)
        self.assertFalse(outcome.fallback_used)

    def test_not_implemented_maps_to_unresolved(self):
        result = ResponseGenerationResult(
            status=STATUS_NOT_IMPLEMENTED, response_text=None,
            backend_kind=BACKEND_KIND_LOCAL_MODEL,
        )
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.status, STATUS_UNRESOLVED)

    def test_nothing_is_guessed(self):
        # Even with a reason/error_code present (should not normally
        # happen for these statuses), UNRESOLVED never invents text.
        result = ResponseGenerationResult(
            status=STATUS_DEFERRED, response_text=None,
            backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK, reason="deferred",
        )
        outcome = build_response_generation_outcome(result)
        self.assertIsNone(outcome.generated_text)


class TestExhaustiveStatusMapping(unittest.TestCase):
    """Every existing ResponseGenerationResult status maps to exactly
    one of the four outcome statuses - none is left unmapped, none maps
    to more than one."""

    def test_all_statuses_produce_a_valid_outcome_status(self):
        cases = (
            (STATUS_GENERATED, "text", None, STATUS_SUCCESS),
            (STATUS_DEFERRED, None, None, STATUS_UNRESOLVED),
            (STATUS_NOT_IMPLEMENTED, None, None, STATUS_UNRESOLVED),
            (STATUS_MODEL_NOT_CONFIGURED, None, None, STATUS_FAILED),
            (STATUS_MODEL_UNAVAILABLE, None, None, STATUS_FAILED),
            (STATUS_MODEL_FAILED, None, None, STATUS_FAILED),
            (STATUS_MODEL_NOT_CONFIGURED, None, BACKEND_KIND_DETERMINISTIC_FALLBACK, STATUS_FALLBACK),
            (STATUS_MODEL_UNAVAILABLE, None, BACKEND_KIND_DETERMINISTIC_FALLBACK, STATUS_FALLBACK),
            (STATUS_MODEL_FAILED, None, BACKEND_KIND_DETERMINISTIC_FALLBACK, STATUS_FALLBACK),
        )
        for status, text, fallback_kind, expected in cases:
            with self.subTest(status=status, fallback_kind=fallback_kind):
                result = ResponseGenerationResult(
                    status=status, response_text=text, backend_kind=BACKEND_KIND_LOCAL_MODEL,
                    fallback_backend_kind=fallback_kind,
                )
                outcome = build_response_generation_outcome(result)
                self.assertEqual(outcome.status, expected)
                self.assertIn(outcome.status, ALL_OUTCOME_STATUSES)


class TestInputValidationAndNoMutation(unittest.TestCase):
    """5. Type safety and read-only behavior."""

    def test_rejects_a_non_result(self):
        with self.assertRaises(TypeError):
            build_response_generation_outcome("not a result")

    def test_rejects_a_non_request(self):
        result = ResponseGenerationResult(status=STATUS_DEFERRED)
        with self.assertRaises(TypeError):
            build_response_generation_outcome(result, request="not a request")

    def test_outcome_constructor_rejects_an_unknown_status(self):
        with self.assertRaises(ValueError):
            ResponseGenerationOutcome("NOT_A_REAL_STATUS")

    def test_building_an_outcome_does_not_mutate_the_result(self):
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="hi", backend_kind=BACKEND_KIND_LOCAL_MODEL,
            metadata={"model_id": "m"}, selected_backend_kind=BACKEND_KIND_LOCAL_MODEL,
        )
        before = copy.deepcopy(result.to_dict())
        build_response_generation_outcome(result)
        self.assertEqual(result.to_dict(), before)

    def test_to_dict_round_trips_every_field(self):
        result = ResponseGenerationResult(
            status=STATUS_MODEL_FAILED, response_text=None, backend_kind=BACKEND_KIND_LOCAL_MODEL,
            reason="failed", inference_status="timeout", error_code="timed_out",
        )
        outcome = build_response_generation_outcome(result)
        as_dict = outcome.to_dict()
        self.assertEqual(as_dict["status"], STATUS_FAILED)
        self.assertEqual(as_dict["failure_reason"],
                         {"error_code": "timed_out", "inference_status": "timeout", "reason": "failed"})
        self.assertFalse(as_dict["fallback_used"])
        self.assertIsNone(as_dict["generated_text"])


# ----------------------------------------------------------------------
# language/locale + compatibility with a real ResponseGenerationRequest
# ----------------------------------------------------------------------
class _PlanCase(unittest.TestCase):
    """Same composition test_response_generation_context.py's _PlanCase
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
        return ResponseGenerationRequest(understanding, context=context.get("context"))


class TestLanguageAndLocalePreservation(_PlanCase):
    """6. language/locale flow through from the request's own
    generation_context (Prompts 426/401) - never recomputed here."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")

    def test_language_is_read_from_the_requests_generation_context(self):
        request = self.request_for("what is python")
        expected_language = request.generation_context["language"]
        result = ResponseGenerationResult(status=STATUS_DEFERRED, backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        outcome = build_response_generation_outcome(result, request=request)
        self.assertEqual(outcome.language, expected_language)

    def test_locale_is_read_from_the_requests_generation_context(self):
        request = self.request_for("what is python")
        expected_locale = request.generation_context["locale"]
        result = ResponseGenerationResult(status=STATUS_DEFERRED, backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        outcome = build_response_generation_outcome(result, request=request)
        self.assertEqual(outcome.locale, expected_locale)

    def test_no_request_means_no_language_or_locale(self):
        result = ResponseGenerationResult(status=STATUS_DEFERRED, backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        outcome = build_response_generation_outcome(result)
        self.assertIsNone(outcome.language)
        self.assertIsNone(outcome.locale)


class TestCompatibilityAndNoRequestMutation(_PlanCase):
    """7. Works with a real, existing ResponseGenerationRequest and
    never mutates it (or the understanding/context it wraps)."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")

    def test_accepts_a_real_response_generation_request(self):
        request = self.request_for("what is python")
        result = ResponseGenerationResult(status=STATUS_DEFERRED, backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        outcome = build_response_generation_outcome(result, request=request)
        self.assertIsInstance(outcome, ResponseGenerationOutcome)

    def test_request_and_understanding_are_unchanged(self):
        request = self.request_for("what is python")
        understanding_before = copy.deepcopy(request.understanding.to_dict())
        plan_before = copy.deepcopy(request.response_plan)
        context_before = copy.deepcopy(request.generation_context)

        result = ResponseGenerationResult(status=STATUS_DEFERRED, backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)
        outcome = build_response_generation_outcome(result, request=request)

        self.assertEqual(request.understanding.to_dict(), understanding_before)
        self.assertEqual(request.response_plan, plan_before)
        self.assertEqual(request.generation_context, context_before)
        # And the returned generation_context is independent - mutating
        # it can never reach the request's own plan/understanding.
        mutated = request.generation_context
        mutated["language"] = "__mutated__"
        self.assertEqual(request.generation_context["language"], context_before["language"])
        self.assertIsInstance(outcome, ResponseGenerationOutcome)


# ----------------------------------------------------------------------
# Integration-level: the real generation flow (LocalLanguageModelBackend /
# DeterministicFallbackBackend / LanguageIntelligenceCore), unmodified.
# ----------------------------------------------------------------------
class TestIntegrationWithRealGenerationFlow(GuardCase):
    """8. SUCCESS, FALLBACK, FAILED and UNRESOLVED each happen from the
    real, unmodified generation flow - not a parallel one built for
    this test."""

    def understanding(self, text=MESSAGE):
        return DeterministicFallbackBackend(UnderstandingEngine()).understand(text)

    def test_success_from_a_ready_local_model(self):
        runtime = TextRuntime(self.config(), MODEL_TEXT)
        backend = LocalLanguageModelBackend(runtime=runtime)
        result = backend.generate_response(self.understanding())
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertEqual(outcome.generated_text, MODEL_TEXT)
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertFalse(outcome.fallback_used)

    def test_failed_when_the_model_is_unavailable_and_no_fallback_is_configured(self):
        runtime = TextRuntime(self.config())
        runtime.dependency_ok = False
        backend = LocalLanguageModelBackend(runtime=runtime)
        result = backend.generate_response(self.understanding())
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertIsNone(outcome.generated_text)
        self.assertFalse(outcome.fallback_used)
        self.assertIsNotNone(outcome.failure_reason)
        self.assertEqual(outcome.failure_reason["error_code"], result.error_code)

    def test_fallback_when_a_fallback_backend_is_configured_for_a_blocked_model(self):
        runtime = TextRuntime(self.config())
        runtime.dependency_ok = False
        core, _ = _core(self)
        core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(core.understanding))
        understanding = core.understand_language(MESSAGE)
        result = core.generate_language_response(understanding)
        self.assertIsNotNone(result.fallback_backend_kind)  # sanity: real code set it
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.status, STATUS_FALLBACK)
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_unresolved_from_the_deterministic_backend_directly(self):
        backend = DeterministicFallbackBackend(UnderstandingEngine())
        understanding = backend.understand(MESSAGE)
        result = backend.generate_response(understanding)
        self.assertEqual(result.status, STATUS_DEFERRED)  # sanity
        outcome = build_response_generation_outcome(result)
        self.assertEqual(outcome.status, STATUS_UNRESOLVED)
        self.assertIsNone(outcome.generated_text)
        self.assertFalse(outcome.fallback_used)


if __name__ == "__main__":
    unittest.main()
