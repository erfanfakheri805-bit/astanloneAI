"""
Tests for Prompt 429 - Expose the structured response-generation outcome
through `LanguageIntelligenceCore`.

`LanguageIntelligenceCore.generate_response()` (language_intelligence/
language_intelligence_core.py) still returns the same
`ResponseGenerationResult` it always did; it now ALSO builds the Prompt 428
`ResponseGenerationOutcome` (SUCCESS / FALLBACK / FAILED / UNRESOLVED) from
that very result and keeps it as `get_last_response_generation_result()`
(`generate_response_outcome()` returns it directly). These tests drive the
real, unmodified generation flow (the Prompt 409/413 test doubles) and check
that every existing behavior is preserved and nothing is mutated.

Run directly:
    python -m unittest tests.test_core_response_generation_outcome -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
    MODEL_FAILURE_STATUSES,
)
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome,
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED,
)

from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT
from tests.test_local_inference_response_generation import TextRuntime


class OutcomeCoreCase(GuardCase):
    """Builds the same cores the earlier stages' tests build."""

    def ready_runtime(self, text=MODEL_TEXT):
        return TextRuntime(self.config(), text)

    def blocked_runtime(self):
        runtime = TextRuntime(self.config())
        runtime.dependency_ok = False
        return runtime

    def core(self, runtime, with_fallback):
        fallback = DeterministicFallbackBackend(UnderstandingEngine()) if with_fallback else None
        return LanguageIntelligenceCore(LocalLanguageModelBackend(runtime=runtime),
                                        fallback_backend=fallback)

    def planned_understanding(self, text=MESSAGE):
        """An understanding that carries a ResponsePlan (Prompt 425)."""
        planner = LanguageIntelligenceCore(DeterministicFallbackBackend(UnderstandingEngine()))
        understanding = planner.understand(text)
        self.assertIsNotNone(understanding.response_plan)  # sanity
        return understanding


class TestCoreReceivesEachOutcome(OutcomeCoreCase):
    def test_success(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        response = core.generate_response(self.understanding())
        outcome = core.get_last_response_generation_result()
        self.assertIsInstance(outcome, ResponseGenerationOutcome)
        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertEqual(outcome.generated_text, MODEL_TEXT)
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertFalse(outcome.fallback_used)
        self.assertIsNone(outcome.failure_reason)
        # the returned result is the same, unchanged, object type/data
        self.assertIsInstance(response, ResponseGenerationResult)
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, MODEL_TEXT)

    def test_fallback(self):
        core = self.core(self.blocked_runtime(), with_fallback=True)
        response = core.generate_response(self.understanding())
        outcome = core.get_last_response_generation_result()
        self.assertEqual(outcome.status, STATUS_FALLBACK)
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIn(response.status, MODEL_FAILURE_STATUSES)
        self.assertIsNone(response.response_text)
        self.assertIsNone(outcome.generated_text)

    def test_failed(self):
        core = self.core(self.blocked_runtime(), with_fallback=False)
        response = core.generate_response(self.understanding())
        outcome = core.get_last_response_generation_result()
        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertFalse(outcome.fallback_used)
        self.assertIsNone(outcome.generated_text)
        self.assertEqual(outcome.backend_kind, response.backend_kind)
        self.assertIn(response.status, MODEL_FAILURE_STATUSES)

    def test_unresolved(self):
        core = LanguageIntelligenceCore(DeterministicFallbackBackend(UnderstandingEngine()))
        response = core.generate_response(self.understanding())
        outcome = core.get_last_response_generation_result()
        self.assertEqual(response.status, STATUS_DEFERRED)  # sanity
        self.assertEqual(outcome.status, STATUS_UNRESOLVED)
        self.assertIsNone(outcome.generated_text)
        self.assertIsNone(outcome.failure_reason)
        self.assertFalse(outcome.fallback_used)
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestFieldsArePreserved(OutcomeCoreCase):
    def test_generated_text_is_preserved_exactly(self):
        for text in ("  padded \n", "Zażółć gęślą — سلام — 你好", "line one\nline two"):
            with self.subTest(text=text):
                core = self.core(self.ready_runtime(text), with_fallback=True)
                response = core.generate_response(self.understanding())
                self.assertEqual(core.get_last_response_generation_result().generated_text,
                                 response.response_text)
                self.assertEqual(response.response_text, text)

    def test_failure_reason_is_preserved(self):
        core = self.core(self.blocked_runtime(), with_fallback=False)
        response = core.generate_response(self.understanding())
        self.assertEqual(core.get_last_response_generation_result().failure_reason, {
            "error_code": response.error_code,
            "inference_status": response.inference_status,
            "reason": response.reason or None,
        })
        self.assertIsNotNone(response.error_code)

    def test_fallback_used_is_preserved(self):
        with_fallback = self.core(self.blocked_runtime(), with_fallback=True)
        with_fallback.generate_response(self.understanding())
        without = self.core(self.blocked_runtime(), with_fallback=False)
        without.generate_response(self.understanding())
        self.assertTrue(with_fallback.get_last_response_generation_result().fallback_used)
        self.assertFalse(without.get_last_response_generation_result().fallback_used)

    def test_metadata_is_preserved_and_independent(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        response = core.generate_response(self.understanding())
        outcome = core.get_last_response_generation_result()
        self.assertEqual(outcome.metadata, response.metadata)
        self.assertIsNotNone(outcome.metadata)
        before = dict(response.metadata)
        outcome.metadata["model_id"] = "changed"
        self.assertEqual(response.metadata, before)

    def test_language_and_locale_are_preserved(self):
        understanding = self.planned_understanding()
        expected = ResponseGenerationRequest(understanding).generation_context
        self.assertIsNotNone(expected)
        core = self.core(self.ready_runtime(), with_fallback=True)
        core.generate_response(understanding)
        outcome = core.get_last_response_generation_result()
        self.assertEqual(outcome.language, expected["language"])
        self.assertEqual(outcome.locale, expected["locale"])

    def test_language_and_locale_are_none_without_a_plan(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        core.generate_response(self.understanding())
        outcome = core.get_last_response_generation_result()
        self.assertIsNone(outcome.language)
        self.assertIsNone(outcome.locale)

    def test_outcome_is_the_same_data_as_building_it_from_the_request_and_result(self):
        understanding = self.planned_understanding()
        core = self.core(self.blocked_runtime(), with_fallback=True)
        response = core.generate_response(understanding)
        expected = build_response_generation_outcome(
            response, request=ResponseGenerationRequest(understanding))
        self.assertEqual(core.get_last_response_generation_result().to_dict(), expected.to_dict())


class TestLatestResultAccessor(OutcomeCoreCase):
    def test_none_before_the_first_response(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        self.assertIsNone(core.get_last_response_generation_result())

    def test_same_object_on_repeated_reads(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        core.generate_response(self.understanding())
        first = core.get_last_response_generation_result()
        self.assertIs(core.get_last_response_generation_result(), first)

    def test_latest_result_replaces_the_previous_one(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        core.generate_response(self.understanding())
        first = core.get_last_response_generation_result()
        core.generate_response(self.understanding())
        second = core.get_last_response_generation_result()
        self.assertIsNot(second, first)
        self.assertEqual((second.status, second.generated_text), (first.status, first.generated_text))

    def test_generate_response_outcome_returns_the_stored_outcome(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        outcome = core.generate_response_outcome(self.understanding())
        self.assertIs(outcome, core.get_last_response_generation_result())
        self.assertEqual(outcome.status, STATUS_SUCCESS)

    def test_a_raising_backend_leaves_no_stale_result(self):
        core = self.core(self.ready_runtime(), with_fallback=False)
        core.generate_response(self.understanding())
        self.assertIsNotNone(core.get_last_response_generation_result())
        with mock.patch.object(core.backend, "generate_response", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                core.generate_response(self.understanding())
        self.assertIsNone(core.get_last_response_generation_result())


class TestExistingCallersRemainCompatible(OutcomeCoreCase):
    def test_deterministic_core_returns_what_its_backend_returns(self):
        backend = DeterministicFallbackBackend(UnderstandingEngine())
        core = LanguageIntelligenceCore(backend)
        understanding = self.understanding()
        direct = backend.generate_response(understanding).to_dict()
        via_core = core.generate_response(understanding).to_dict()
        direct.pop("selected_backend_kind")
        via_core.pop("selected_backend_kind")
        self.assertEqual(via_core, direct)

    def test_return_type_and_backend_selection_are_unchanged(self):
        for runtime, with_fallback in ((self.ready_runtime(), True), (self.blocked_runtime(), True),
                                        (self.blocked_runtime(), False)):
            core = self.core(runtime, with_fallback)
            response = core.generate_response(self.understanding())
            self.assertIsInstance(response, ResponseGenerationResult)
            self.assertIsNotNone(core.last_backend_selection)
            self.assertEqual(response.selected_backend_kind,
                             core.last_backend_selection.selected_backend_kind)

    def test_one_backend_call_only(self):
        runtime = self.ready_runtime()
        core = self.core(runtime, with_fallback=True)
        core.generate_response(self.understanding())
        core.get_last_response_generation_result()
        self.assertEqual(runtime.generate_calls, 1)

    def test_a_failure_to_build_the_outcome_never_breaks_the_response(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        target = "language_intelligence.language_intelligence_core.build_response_generation_outcome"
        with mock.patch(target, side_effect=RuntimeError("boom")):
            response = core.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertIsNone(core.get_last_response_generation_result())

    def test_a_non_result_backend_return_is_unchanged_and_has_no_outcome(self):
        backend = DeterministicFallbackBackend(UnderstandingEngine())
        core = LanguageIntelligenceCore(backend)
        sentinel = object()
        with mock.patch.object(backend, "generate_response", return_value=sentinel):
            self.assertIs(core.generate_response(self.understanding()), sentinel)
        self.assertIsNone(core.get_last_response_generation_result())


class TestNothingIsMutated(OutcomeCoreCase):
    def test_request_understanding_plan_and_context_are_not_mutated(self):
        understanding = self.planned_understanding()
        context = {"topic": "python"}
        request = ResponseGenerationRequest(understanding, context=context)
        before = (copy.deepcopy(understanding.to_dict()), copy.deepcopy(request.response_plan),
                  copy.deepcopy(request.generation_context), copy.deepcopy(context))
        core = self.core(self.blocked_runtime(), with_fallback=True)
        core.generate_response(understanding, context=context)
        self.assertEqual(understanding.to_dict(), before[0])
        self.assertEqual(request.response_plan, before[1])
        self.assertEqual(request.generation_context, before[2])
        self.assertEqual(context, before[3])

    def test_the_outcome_can_be_changed_without_reaching_the_core_or_result(self):
        core = self.core(self.blocked_runtime(), with_fallback=False)
        response = core.generate_response(self.understanding())
        before = copy.deepcopy(response.to_dict())
        outcome = core.get_last_response_generation_result()
        outcome.failure_reason["reason"] = "changed"
        self.assertEqual(response.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
