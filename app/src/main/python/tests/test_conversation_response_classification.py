"""
Tests for Prompt 432 - Conversation Response Classification.

`ConversationResponse.classification` (language_intelligence/
conversation_response.py) is NORMAL / FALLBACK / FAILURE / UNRESOLVED, a
fixed function of the existing `status`; it never changes any other field.

Run directly:
    python -m unittest tests.test_conversation_response_classification -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.conversation_response import (
    ConversationResponse, build_conversation_response, classify_status, ALL_CLASSIFICATIONS,
    CLASSIFICATION_NORMAL, CLASSIFICATION_FALLBACK, CLASSIFICATION_FAILURE, CLASSIFICATION_UNRESOLVED,
)
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
    STATUS_MODEL_FAILED, STATUS_NOT_IMPLEMENTED,
)
from language_intelligence.response_generation_outcome import (
    build_response_generation_outcome, STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED,
)

from tests.test_core_response_generation_outcome import OutcomeCoreCase
from tests.test_pre_inference_readiness_guard import MODEL_TEXT
from tests.test_conversation_response import (
    success_result, fallback_result, failed_result, unresolved_result, FAILURE,
)


class TestMapping(unittest.TestCase):
    def test_success_is_normal(self):
        response = build_conversation_response(success_result())
        self.assertEqual((response.status, response.classification), (STATUS_SUCCESS, CLASSIFICATION_NORMAL))

    def test_fallback_is_fallback(self):
        response = build_conversation_response(fallback_result("reply"))
        self.assertEqual((response.status, response.classification),
                         (STATUS_FALLBACK, CLASSIFICATION_FALLBACK))

    def test_failed_is_failure(self):
        response = build_conversation_response(failed_result())
        self.assertEqual((response.status, response.classification), (STATUS_FAILED, CLASSIFICATION_FAILURE))

    def test_unresolved_is_unresolved(self):
        for result in (unresolved_result(), ResponseGenerationResult(STATUS_NOT_IMPLEMENTED)):
            with self.subTest(status=result.status):
                response = build_conversation_response(result)
                self.assertEqual((response.status, response.classification),
                                 (STATUS_UNRESOLVED, CLASSIFICATION_UNRESOLVED))

    def test_fixed_small_set_and_one_to_one_mapping(self):
        self.assertEqual(ALL_CLASSIFICATIONS, ("NORMAL", "FALLBACK", "FAILURE", "UNRESOLVED"))
        mapped = [classify_status(s) for s in (STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED)]
        self.assertEqual(mapped, list(ALL_CLASSIFICATIONS))
        self.assertIsNone(classify_status("anything else"))
        self.assertIsNone(classify_status(None))

    def test_classification_cannot_be_supplied_or_changed(self):
        with self.assertRaises(TypeError):
            ConversationResponse(status=STATUS_FAILED, classification=CLASSIFICATION_NORMAL)
        response = build_conversation_response(failed_result())
        with self.assertRaises(AttributeError):
            response.classification = CLASSIFICATION_NORMAL

    def test_invalid_results_are_never_classified_as_normal(self):
        for result in (ResponseGenerationResult(STATUS_GENERATED, response_text=""),
                       ResponseGenerationResult(STATUS_MODEL_FAILED)):
            with self.subTest(status=result.status):
                response = build_conversation_response(result)
                self.assertNotEqual(response.classification, CLASSIFICATION_NORMAL)
                self.assertEqual(response.classification, classify_status(response.status))

    def test_classification_is_in_to_dict_and_deterministic(self):
        result = failed_result()
        first = build_conversation_response(result).to_dict()
        self.assertEqual(first["classification"], CLASSIFICATION_FAILURE)
        self.assertEqual(first, build_conversation_response(result).to_dict())


class TestNothingElseChanges(unittest.TestCase):
    """Every pre-existing field still equals what the outcome/result carry."""

    def check_unchanged(self, result, request=None):
        before = copy.deepcopy(result.to_dict())
        outcome = build_response_generation_outcome(result, request=request)
        response = build_conversation_response(result, request=request)
        self.assertEqual(response.status, outcome.status)
        self.assertEqual(response.response_text, outcome.generated_text)
        self.assertEqual(response.backend_kind, outcome.backend_kind)
        self.assertEqual(response.language, outcome.language)
        self.assertEqual(response.locale, outcome.locale)
        self.assertEqual(response.fallback_used, outcome.fallback_used)
        self.assertEqual(response.failure_reason and dict(response.failure_reason), outcome.failure_reason)
        self.assertEqual(response.metadata and dict(response.metadata), outcome.metadata)
        self.assertEqual(response.generation_status, result.status)
        self.assertEqual(response.generation_backend_kind, result.backend_kind)
        self.assertEqual(result.to_dict(), before)  # the underlying result is untouched
        return response

    def test_success_fields(self):
        response = self.check_unchanged(success_result("Zażółć — 你好\n", metadata={"model_id": "m"}))
        self.assertEqual(response.response_text, "Zażółć — 你好\n")
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(dict(response.metadata), {"model_id": "m"})

    def test_fallback_fields(self):
        response = self.check_unchanged(fallback_result("reply"))
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(response.response_text, "reply")

    def test_failed_fields(self):
        response = self.check_unchanged(failed_result())
        self.assertEqual(dict(response.failure_reason), FAILURE)
        self.assertFalse(response.fallback_used)
        self.assertIsNone(response.response_text)

    def test_unresolved_fields(self):
        response = self.check_unchanged(unresolved_result())
        self.assertIsNone(response.response_text)
        self.assertIsNone(response.failure_reason)

    def test_validation_fields_are_unchanged(self):
        response = build_conversation_response(fallback_result(None))
        self.assertFalse(response.valid)
        self.assertEqual(response.status, STATUS_FALLBACK)
        self.assertEqual(response.classification, CLASSIFICATION_FALLBACK)
        self.assertEqual(len(response.validation_issues), 1)


class TestCoreIntegration(OutcomeCoreCase):
    def test_success_through_core(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        result = core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual((response.status, response.classification), (STATUS_SUCCESS, CLASSIFICATION_NORMAL))
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertEqual(response.response_text, result.response_text)
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(dict(response.metadata), result.metadata)

    def test_fallback_through_core(self):
        core = self.core(self.blocked_runtime(), with_fallback=True)
        core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual((response.status, response.classification),
                         (STATUS_FALLBACK, CLASSIFICATION_FALLBACK))
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.response_text)

    def test_failed_through_core(self):
        core = self.core(self.blocked_runtime(), with_fallback=False)
        result = core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual((response.status, response.classification), (STATUS_FAILED, CLASSIFICATION_FAILURE))
        self.assertEqual(response.failure_reason["error_code"], result.error_code)

    def test_unresolved_through_core(self):
        from understanding.engine import UnderstandingEngine
        core = LanguageIntelligenceCore(DeterministicFallbackBackend(UnderstandingEngine()))
        core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual((response.status, response.classification),
                         (STATUS_UNRESOLVED, CLASSIFICATION_UNRESOLVED))

    def test_language_and_locale_through_core(self):
        understanding = self.planned_understanding()
        expected = ResponseGenerationRequest(understanding).generation_context
        core = self.core(self.ready_runtime(), with_fallback=True)
        core.generate_response(understanding)
        response = core.get_last_conversation_response()
        self.assertEqual((response.language, response.locale), (expected["language"], expected["locale"]))
        self.assertEqual(response.classification, CLASSIFICATION_NORMAL)

    def test_generate_conversation_response_carries_the_classification(self):
        core = self.core(self.blocked_runtime(), with_fallback=False)
        response = core.generate_conversation_response(self.understanding())
        self.assertIs(response, core.get_last_conversation_response())
        self.assertEqual(response.classification, CLASSIFICATION_FAILURE)

    def test_existing_callers_remain_compatible(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        result = core.generate_response(self.understanding())
        self.assertIsInstance(result, ResponseGenerationResult)
        self.assertEqual((result.status, result.response_text), (STATUS_GENERATED, MODEL_TEXT))
        self.assertFalse(hasattr(result, "classification"))  # raw result unchanged
        response = core.get_last_conversation_response()
        self.assertEqual(response.response_text, MODEL_TEXT)  # text callers keep working
        self.assertEqual(core.get_last_response_generation_result().status, STATUS_SUCCESS)
        self.assertTrue(core.get_last_response_generation_validation().valid)


if __name__ == "__main__":
    unittest.main()
